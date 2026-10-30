#!/usr/bin/env python3
"""Write a commit's review record from the verifier's own result — never from the author's summary.

The verifier session (started by verify_fresh.sh, a fresh session that did not write the code) calls this
with a JSON result. This script decides the verdict mechanically and refuses records that overclaim:

  - every required lane must have run on exactly this commit (no carrying an older round's lane)
  - every P0/P1 finding needs a validator verdict (CONFIRMED / PLAUSIBLE / REJECTED)
  - the live lane needs evidence, or `not-applicable` with a reason
  - the verify verdict is read from <gate>/<sha>.verify.json, not from the JSON
  - with `--issues`, every acceptance criterion of the issues the branch closes has a verdict and its evidence

It writes <git common dir>/gate/<sha>.review.md (first line read by push gates) with a provenance comment
naming the verifier session, and appends one review-log row per finding to ~/.claude/review-log/<repo>.tsv.

Why (hhmode log.md, 2026-10-29): the author wrote these records by hand. Final commits were recorded as
reviewed by two lanes when one had run, a P1 skipped its validator, and no review-log row was written for 11
reviewed commits. pstack: "Only a verdict from an agent that did not write the code counts."

Usage: record_review.py --repo <worktree> --result <result.json> --report <report.md> --session <uuid>
                        --mode standard|fix [--since <reviewed ancestor sha>] [--issues <issues.md>]
       record_review.py --repo <worktree> --carry <reviewed ancestor sha>

A re-review is proportional to what changed since the last one (pstack autopilot-full): with `--since`, the
review lanes read only the diff after a commit on this branch whose verifier record is PASS or ISSUES in at least
this mode. Verify and live still run on this commit. A `fix` record is a re-review of a small change (lanes bug,
verify, live) and always needs `--since`. With `--carry`, a change to wording only (review_weight.py) gets its
record from the earlier PASS record, with no verifier session: such a record is not a review of its own, so no later
`--since` can start from it.

Acceptance criteria (forms.py): verify_fresh.sh writes the issues the branch closes to a file (`# Issue #<n>: <title>`
and the body, one after another). The result then carries one `criteria` entry for each criterion in them, judged by
the verifier with evidence; a criterion that is not met makes the verdict ISSUES, like a confirmed P1. The record opens
with a summary table, so a reader sees the verdict, risk and criteria before the report.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import shutil
import subprocess
import sys

import forms

# `fix` is a re-review of a small change (review_weight.py): no rules lane and no Codex, since the standard review
# underneath already ran them (pstack autopilot-full: a minor fix gets a single verifier at the new head).
# There was a `full` mode with a Fable bug reviewer (lane bug-fable) on top of standard, and before that a bug reviewer
# given only the diff. Both were dropped: the review logs (~/.claude/review-log/*.tsv) show every P0/P1 Fable raised
# was also raised by Opus; Fable alone raised only P2/P3. Codex (bug-gpt) now gives a second model's view, and Fable
# costs tokens (user decision 2026-10-30). Old records that say `full` still parse and count like standard.
REQUIRED = {
    "standard": ("bug", "rules", "bug-gpt", "verify", "live"),
    "fix": ("bug", "verify", "live"),
}
# bug-gpt is a reviewer from another company (Codex), in standard mode: every other lane is an Anthropic model, and a
# same-family reviewer shares the author's blind spots (pstack runs Opus with Grok in its reviewer panels).
VALIDATED = {"CONFIRMED", "PLAUSIBLE", "REJECTED"}
SERIOUS = {"P0", "P1"}
SEVERITIES = {"P0", "P1", "P2", "P3", "rule"}
# references/tiers.md. Below high, scripts/automerge.py merges without the user, so it is required, never defaulted.
TIERS = {"low", "medium", "high"}
# Who raised a finding: lane names, joined with "+" when several raised it. The log had 25 spellings of four
# reviewers ("opus", "Opus", "Opusfull", "Fable)", ...), so the fix rate per reviewer could not be counted.
# bug-fable stays so that old logs and records are still valid; no new record has that lane.
RAISERS = {"bug", "rules", "bug-fable", "bug-gpt", "live", "verify"}
# The verifier's verdict on one acceptance criterion. `unclear` is for what this commit cannot decide; the merge check
# sends such a PR to the user (merge-check.md).
STATUSES = {"met", "not-met", "unclear"}
ISSUE_HEAD = re.compile(r"^# Issue #(\d+):[^\n]*$", re.M)


class Refused(Exception):
    """The result does not support a record. The message says what is missing."""


def git(repo: pathlib.Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def gate_dir(repo: pathlib.Path) -> pathlib.Path:
    common = pathlib.Path(git(repo, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = (repo / common).resolve()
    return common / "gate"


def repo_name(repo: pathlib.Path) -> str:
    common = pathlib.Path(git(repo, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = (repo / common).resolve()
    return common.parent.name


def verify_verdict(gdir: pathlib.Path, sha: str) -> str:
    path = gdir / f"{sha}.verify.json"
    if not path.exists():
        raise Refused(f"no verify record at {path} — run the repo's verify step on this commit first")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("sha") not in (sha, sha[:7]) and not str(data.get("sha", "")).startswith(sha[:7]):
        raise Refused(f"{path.name} names another commit ({data.get('sha')})")
    verdict = str(data.get("verdict", "")).upper()
    if verdict not in ("PASS", "FAIL", "BLOCKED"):
        raise Refused(f"{path.name} has verdict {data.get('verdict')!r}; expected PASS, FAIL or BLOCKED")
    return verdict


def verify_from_lane(result: dict, sha: str) -> str:
    """For a repo with no verify step (no scripts/verify.py): the verifier ran the repo's tests itself and
    reports them as a `verify` lane with evidence. Still the verifier's word, never the author's."""
    ln = next((x for x in result.get("lanes", []) if x.get("lane") == "verify"), None)
    if ln is None:
        raise Refused("no scripts/verify.py here, so a `verify` lane with the test command and output is required")
    if ln.get("status") == "blocked":
        return "BLOCKED"
    if ln.get("sha") != sha:
        raise Refused(f"verify lane ran on {ln.get('sha')!r}, not on {sha}")
    if not (ln.get("evidence") or "").strip():
        raise Refused("verify lane without evidence — paste the test command and its output")
    verdict = str(ln.get("verdict", "")).upper()
    if verdict not in ("PASS", "FAIL"):
        raise Refused(f"verify lane verdict must be PASS or FAIL, got {ln.get('verdict')!r}")
    return verdict


def issue_criteria(text: str) -> list[tuple[int, str]]:
    """(issue number, criterion id) for each acceptance criterion in an issues file: `# Issue #<n>: <title>` and the
    issue's body, one after another."""
    parts = ISSUE_HEAD.split(text)                  # [before the first header, number, body, number, body, ...]
    return [(int(n), ac) for n, body in zip(parts[1::2], parts[2::2]) for ac in forms.criteria(body)]


def check_criteria(result: dict, expected: list[tuple[int, str]]) -> list[dict]:
    """The result's verdict on each expected criterion, in order, or raise Refused: a criterion left out, a status
    that is not met / not-met / unclear, or a met / not-met without evidence."""
    got = {(c.get("issue"), c.get("id")): c for c in result.get("criteria", [])}
    out = []
    for issue, ac in expected:
        c = got.get((issue, ac))
        if c is None:
            raise Refused(f"result.criteria has no entry for {ac} of issue #{issue} — judge it, with "
                          f'{{"issue": {issue}, "id": "{ac}", "status": ..., "evidence": ...}} (issue as a number)')
        if c.get("status") not in STATUSES:
            raise Refused(f"{ac} of issue #{issue} has status {c.get('status')!r}; use one of {sorted(STATUSES)}")
        if c["status"] != "unclear" and not (c.get("evidence") or "").strip():
            raise Refused(f"{ac} of issue #{issue} is {c['status']} without evidence — run it or point to file:line")
        out.append(c)
    return out


def check(result: dict, sha: str, verify: str, expected: list[tuple[int, str]] = ()) -> str:
    """Return the verdict, or raise Refused. Pure: no files, no git. `expected`: the criteria of the issues the branch
    closes, each of which the result must judge."""
    if result.get("sha") != sha:
        raise Refused(f"result.sha {result.get('sha')!r} is not the commit under review {sha}")
    mode = result.get("mode")
    if mode not in REQUIRED:
        raise Refused(f"mode must be one of {sorted(REQUIRED)}, got {mode!r}")
    if result.get("tier") not in TIERS:
        raise Refused(f"tier must be one of {sorted(TIERS)} (references/tiers.md), got {result.get('tier')!r}")
    lanes = {ln.get("lane"): ln for ln in result.get("lanes", [])}
    blocked = []
    for name in REQUIRED[mode]:
        if name == "verify":
            continue                                  # read from the verify record, below
        ln = lanes.get(name)
        if ln is None:
            raise Refused(f"lane {name!r} is missing — every {mode} lane runs on this commit")
        status = ln.get("status")
        if status == "blocked":
            blocked.append(f"{name}: {ln.get('reason') or 'no reason given'}")
            continue
        if name == "live" and status == "not-applicable":
            if not (ln.get("reason") or "").strip():
                raise Refused("live lane is not-applicable without a reason")
            continue
        if ln.get("sha") != sha:
            raise Refused(f"lane {name!r} ran on {ln.get('sha')!r}, not on {sha} — re-run it on this commit")
        if status != "ran":
            raise Refused(f"lane {name!r} has status {status!r}; expected ran / blocked / not-applicable")
        if name == "live" and not (ln.get("evidence") or "").strip():
            raise Refused("live lane ran without evidence — paste the command and its output")
    if verify == "BLOCKED":
        blocked.append("verify: BLOCKED in the verify record")
    findings = result.get("findings", [])
    for f in findings:
        # Exact values only: "p1" or "high" would otherwise slip past the validator check below.
        if f.get("severity") not in SEVERITIES:
            raise Refused(f"{f.get('id')} has severity {f.get('severity')!r}; use one of {sorted(SEVERITIES)}")
        if f.get("severity") in SERIOUS and f.get("validation") not in VALIDATED:
            raise Refused(f"{f.get('id')} is {f.get('severity')} without a validator verdict "
                          f"(got {f.get('validation')!r}) — spawn finding-validator for it")
        raisers = str(f.get("raised_by", "")).split("+")
        if not all(r in RAISERS for r in raisers):
            raise Refused(f"{f.get('id')} has raised_by {f.get('raised_by')!r}; use lane names from "
                          f"{sorted(RAISERS)}, joined with '+'")
    judged = check_criteria(result, expected)
    if blocked:
        return "BLOCKED"
    live_issue = [f for f in findings
                  if (f.get("severity") in SERIOUS and f.get("validation") in {"CONFIRMED", "PLAUSIBLE"})
                  or f.get("severity") == "rule"]
    if live_issue or verify == "FAIL" or any(c["status"] == "not-met" for c in judged):
        return "ISSUES"
    return "PASS"


# A review can start after one at least as strong. `full` is the old name of standard's strength.
STRENGTH = {"fix": 0, "standard": 1, "full": 1}
# `carry` records are left out on purpose: they are not a review, so nothing starts from them.
SINCE_RE = re.compile(r"^\*\*Review: (PASS|ISSUES)\*\* · [0-9a-f]{7,40} · (fix|standard|full)\b")


def reviewed(text: str) -> tuple[str, str] | None:
    """(verdict, mode) of a verifier record, or None when it does not count as a review: no verifier session, a
    carried record, or BLOCKED (a blocked lane still writes a record; independent review of hhmode e6968d0 reproduced a
    PASS scoped to a BLOCKED commit whose bug lane never ran)."""
    m = SINCE_RE.match(text)
    return (m.group(1), m.group(2)) if m and "verifier-session:" in text else None


def reviewed_as(text: str) -> str | None:
    """The mode a verifier record covers, or None when it does not count as a review (see `reviewed`)."""
    got = reviewed(text)
    return got[1] if got else None


def carryable(text: str) -> bool:
    """Whether a later commit that changed wording only may take this record's result: a verifier's PASS whose tests
    passed too."""
    got = reviewed(text)
    return got is not None and got[0] == "PASS" and "; verify: PASS;" in text


def check_since(repo: pathlib.Path, gdir: pathlib.Path, sha: str, since: str, mode: str) -> str:
    """The full sha of `since`, or raise Refused. A review limited to the diff after `since` stands only if
    `since` itself was reviewed by a verifier, every lane ran, in at least this mode, and it lies on this
    commit's history."""
    full = git(repo, "rev-parse", since)
    if full == sha:
        raise Refused("--since names the commit under review itself")
    if subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", full, sha]).returncode != 0:
        raise Refused(f"--since {full[:7]} is not an ancestor of {sha[:7]}")
    rec = gdir / f"{full}.review.md"
    got = reviewed_as(rec.read_text(encoding="utf-8")) if rec.exists() else None
    if got is None:
        raise Refused(f"--since {full[:7]} has no PASS or ISSUES verifier record, so the diff before it was never "
                      "fully reviewed")
    if STRENGTH[got] < STRENGTH[mode]:
        raise Refused(f"--since {full[:7]} was reviewed in {got} mode; a {mode} review cannot start after it")
    return full


def render_carry(sha: str, since: str, paths: list[str], tier: str | None, verify: str = "PASS") -> str:
    """The record of a commit that only changed wording, taken from the PASS record of `since`. The first line is
    what the gates read (automerge.HEAD_RE: the mode is `carry`, and its `since` makes automerge read the earlier
    record's tiers too). The tests passed on `since`: carryable() requires it."""
    s7 = since[:7]
    what = f"Only wording changed since {s7} ({', '.join(paths)})" if paths else f"Nothing changed since {s7}"
    return (f"**Review: PASS** · {sha[:7]} · carry · since {s7} · carried\n\n"
            f"{what}, so the review of {s7} carries over and no verifier session ran on this commit.\n\n"
            f"<!-- verifier-session: carried-from-{since}; verify: {verify}; {f'tier: {tier}; ' if tier else ''}"
            f"lanes: carried@{s7} -->\n")


def carry(repo: pathlib.Path, since: str) -> pathlib.Path:
    """Write HEAD's record from the PASS record of `since`, or raise Refused. The weight is decided here too, not
    trusted from the caller: a commit that changed code must never get a record without a verifier."""
    import review_weight        # here, not at the top: review_weight imports this module
    sha = git(repo, "rev-parse", "HEAD")
    full = git(repo, "rev-parse", since)
    if full == sha:
        raise Refused("--carry names the commit itself")
    if subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", full, sha]).returncode != 0:
        raise Refused(f"--carry {full[:7]} is not an ancestor of {sha[:7]}")
    gdir = gate_dir(repo)
    rec = gdir / f"{full}.review.md"
    text = rec.read_text(encoding="utf-8") if rec.exists() else ""
    if not carryable(text):
        raise Refused(f"{full[:7]} has no verifier record with review PASS and tests PASS to carry")
    kind, why = review_weight.weight(repo, full, sha)
    if kind != "carry":
        raise Refused(f"this change is not wording only ({kind}): {why}")
    # The tests: a verify record on this commit decides, and a FAIL or BLOCKED one is never carried over as PASS
    # (verifier and Codex on 9aadb3c). A repo with scripts/verify.py needs one; elsewhere the earlier PASS stands,
    # since only wording nobody executes changed.
    own = gdir / f"{sha}.verify.json"
    if own.exists():
        verify = verify_verdict(gdir, sha)
        if verify != "PASS":
            raise Refused(f"{sha[:7]} has a verify record of {verify}; a carried record would hide it")
    elif (repo / "scripts" / "verify.py").exists():
        raise Refused(f"no verify record for {sha[:7]}: run the repo's verify step on this commit, then carry")
    else:
        verify = "PASS"
    tier = re.search(r"; tier: (\w+); lanes:", text)
    out = gdir / f"{sha}.review.md"
    out.write_text(render_carry(sha, full, review_weight.changed_paths(repo, full, sha),
                                tier.group(1) if tier else None, verify), encoding="utf-8")
    gpt = gdir / f"{full}.gpt.md"
    if gpt.exists():            # automerge reads the Codex tier next to the record
        shutil.copyfile(gpt, gdir / f"{sha}.gpt.md")
    return out


def cell(value: object) -> str:
    """One table cell: a pipe or a line break in a command's output must not split the row."""
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def findings_count(result: dict) -> str:
    """`P0 0 · P1 0 · P2 1 · P3 2` over the findings that stand (not REJECTED); rule violations are added when any."""
    kept = [f for f in result.get("findings", []) if f.get("validation") != "REJECTED"]
    text = " · ".join(f"{sev} {sum(f.get('severity') == sev for f in kept)}" for sev in ("P0", "P1", "P2", "P3"))
    rules = sum(f.get("severity") == "rule" for f in kept)
    return text + (f" · rule {rules}" if rules else "")


def summary(verdict: str, result: dict, verify: str, judged: list[dict]) -> str:
    """The table under the first line: the answers a reader wants before the report."""
    live = next((ln.get("status") for ln in result.get("lanes", []) if ln.get("lane") == "live"), None) or "—"
    met = f"{sum(c['status'] == 'met' for c in judged)}/{len(judged)} met" if judged else "—"
    return ("| Verdict | Risk | Tests | Live run | Findings | Acceptance criteria |\n|---|---|---|---|---|---|\n"
            f"| {verdict} | {result['tier']} | {verify} | {live} | {findings_count(result)} | {met} |")


def criteria_table(judged: list[dict]) -> str:
    rows = "\n".join(f"| #{c['issue']} | {cell(c['id'])} | {c['status']} | {cell(c.get('evidence') or '—')} |"
                      for c in judged)
    return f"### Acceptance criteria\n\n| Issue | Criterion | Status | Evidence |\n|---|---|---|---|\n{rows}"


def render(verdict: str, sha: str, result: dict, report: str, session: str, verify: str,
           since: str | None = None, expected: list[tuple[int, str]] = ()) -> str:
    lanes = ",".join(f"{ln.get('lane')}@{(ln.get('sha') or '-')[:7]}:{ln.get('status')}"
                     for ln in result.get("lanes", []))
    scope = f" · since {since[:7]}" if since else ""
    head = f"**Review: {verdict}** · {sha[:7]} · {result['mode']}{scope} · verifier {session[:8]}"
    judged = check_criteria(result, expected)
    # The first line stays as it was: automerge.HEAD_RE, push_gate and SINCE_RE read it. `verify:` lets the launcher
    # print the Verify line for a repo that has no verify.json.
    top = [summary(verdict, result, verify, judged)] + ([criteria_table(judged)] if judged else [])
    return (f"{head}\n\n" + "\n\n".join(top) + f"\n\n{report.strip()}\n\n"
            f"<!-- verifier-session: {session}; verify: {verify}; tier: {result['tier']}; lanes: {lanes} -->\n")


def log_rows(result: dict, sha: str, verdict: str) -> list[str]:
    today = dt.date.today().isoformat()
    mode = result["mode"]
    rows = []
    for f in result.get("findings", []):
        rows.append("\t".join([today, sha[:7], mode, str(f.get("id", "-")), str(f.get("severity", "-")),
                               str(f.get("where", "-")), str(f.get("raised_by", "-")),
                               str(f.get("validation", "-")), str(f.get("title", "")).replace("\t", " ")]))
    if not rows:
        rows.append("\t".join([today, sha[:7], mode, "-", "-", "-", "verifier", "none", f"no findings ({verdict})"]))
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", required=True, type=pathlib.Path)
    ap.add_argument("--result", type=pathlib.Path)
    ap.add_argument("--report", type=pathlib.Path)
    ap.add_argument("--session")
    ap.add_argument("--mode", choices=sorted(REQUIRED),
                    help="the mode the launcher asked for; the result must match it")
    ap.add_argument("--carry", metavar="SINCE",
                    help="write this commit's record from the PASS record of SINCE, no verifier (wording-only change)")
    ap.add_argument("--since", help="the review lanes read only the diff after this reviewed ancestor")
    ap.add_argument("--issues", type=pathlib.Path,
                    help="the issues the branch closes (verify_fresh.sh writes it); each criterion must be judged")
    ap.add_argument("--log-dir", type=pathlib.Path, default=pathlib.Path.home() / ".claude" / "review-log")
    a = ap.parse_args(argv)

    repo = a.repo.resolve()
    sha = git(repo, "rev-parse", "HEAD")
    if a.carry:
        try:
            out = carry(repo, a.carry)
        except Refused as e:
            print(f"REFUSED: {e}", file=sys.stderr)
            return 2
        print(f"**Review: PASS** · {sha[:7]} — carried from {a.carry[:7]}, wrote {out}")
        return 0
    for flag in ("result", "report", "session", "mode"):
        if getattr(a, flag) is None:
            ap.error(f"--{flag} is required unless --carry is given")
    result = json.loads(a.result.read_text(encoding="utf-8"))
    gdir = gate_dir(repo)
    expected = issue_criteria(a.issues.read_text(encoding="utf-8")) if a.issues else []
    try:
        # A fix is judged against the diff after an earlier review: without one, nothing says what it fixed.
        if a.mode == "fix" and not a.since:
            raise Refused("a fix record needs --since, the reviewed commit it fixes")
        # The launcher's mode, not the verifier's: a `standard` request reported as `fix` would skip lanes.
        if result.get("mode") != a.mode:
            raise Refused(f"result.mode is {result.get('mode')!r} but the launcher asked for {a.mode!r}")
        has_verify_step = (repo / "scripts" / "verify.py").exists()
        verify = verify_verdict(gdir, sha) if has_verify_step else verify_from_lane(result, sha)
        verdict = check(result, sha, verify, expected)
        since = check_since(repo, gdir, sha, a.since, a.mode) if a.since else None
    except Refused as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2

    gdir.mkdir(parents=True, exist_ok=True)
    out = gdir / f"{sha}.review.md"
    out.write_text(render(verdict, sha, result, a.report.read_text(encoding="utf-8"), a.session, verify, since,
                          expected), encoding="utf-8")
    a.log_dir.mkdir(parents=True, exist_ok=True)
    with (a.log_dir / f"{repo_name(repo)}.tsv").open("a", encoding="utf-8") as fh:
        fh.write("\n".join(log_rows(result, sha, verdict)) + "\n")
    print(f"**Review: {verdict}** · {sha[:7]} — wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
