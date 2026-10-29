#!/usr/bin/env python3
"""Write a commit's review record from the verifier's own result — never from the author's summary.

The verifier session (started by verify_fresh.sh, a fresh session that did not write the code) calls this
with a JSON result. This script decides the verdict mechanically and refuses records that overclaim:

  - every required lane must have run on exactly this commit (no carrying an older round's lane)
  - every P0/P1 finding needs a validator verdict (CONFIRMED / PLAUSIBLE / REJECTED)
  - the live lane needs evidence, or `not-applicable` with a reason
  - the verify verdict is read from <gate>/<sha>.verify.json, not from the JSON

It writes <git common dir>/gate/<sha>.review.md (first line read by push gates) with a provenance comment
naming the verifier session, and appends one review-log row per finding to ~/.claude/review-log/<repo>.tsv.

Why (hhmode log.md, 2026-10-29): the author wrote these records by hand. Final commits were recorded as
reviewed by two lanes when one had run, a P1 skipped its validator, and no review-log row was written for 11
reviewed commits. pstack: "Only a verdict from an agent that did not write the code counts."

Usage: record_review.py --repo <worktree> --result <result.json> --report <report.md> --session <uuid>
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import subprocess
import sys

REQUIRED = {
    "standard": ("bug", "rules", "verify", "live"),
    "full": ("bug", "rules", "bug-diff-only", "bug-fable", "verify", "live"),
}
VALIDATED = {"CONFIRMED", "PLAUSIBLE", "REJECTED"}
SERIOUS = {"P0", "P1"}


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
    return str(data.get("verdict", "")).upper()


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


def check(result: dict, sha: str, verify: str) -> str:
    """Return the verdict, or raise Refused. Pure: no files, no git."""
    if result.get("sha") != sha:
        raise Refused(f"result.sha {result.get('sha')!r} is not the commit under review {sha}")
    mode = result.get("mode")
    if mode not in REQUIRED:
        raise Refused(f"mode must be one of {sorted(REQUIRED)}, got {mode!r}")
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
        if f.get("severity") in SERIOUS and f.get("validation") not in VALIDATED:
            raise Refused(f"{f.get('id')} is {f.get('severity')} without a validator verdict "
                          f"(got {f.get('validation')!r}) — spawn finding-validator for it")
    if blocked:
        return "BLOCKED"
    live_issue = [f for f in findings
                  if (f.get("severity") in SERIOUS and f.get("validation") in {"CONFIRMED", "PLAUSIBLE"})
                  or f.get("severity") == "rule"]
    if live_issue or verify == "FAIL":
        return "ISSUES"
    return "PASS"


def render(verdict: str, sha: str, result: dict, report: str, session: str) -> str:
    lanes = ",".join(f"{ln.get('lane')}@{(ln.get('sha') or '-')[:7]}:{ln.get('status')}"
                     for ln in result.get("lanes", []))
    head = f"**Review: {verdict}** · {sha[:7]} · {result['mode']} · verifier {session[:8]}"
    return f"{head}\n\n{report.strip()}\n\n<!-- verifier-session: {session}; lanes: {lanes} -->\n"


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
    ap.add_argument("--result", required=True, type=pathlib.Path)
    ap.add_argument("--report", required=True, type=pathlib.Path)
    ap.add_argument("--session", required=True)
    ap.add_argument("--log-dir", type=pathlib.Path, default=pathlib.Path.home() / ".claude" / "review-log")
    a = ap.parse_args(argv)

    repo = a.repo.resolve()
    sha = git(repo, "rev-parse", "HEAD")
    result = json.loads(a.result.read_text(encoding="utf-8"))
    gdir = gate_dir(repo)
    try:
        has_verify_step = (repo / "scripts" / "verify.py").exists()
        verify = verify_verdict(gdir, sha) if has_verify_step else verify_from_lane(result, sha)
        verdict = check(result, sha, verify)
    except Refused as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2

    gdir.mkdir(parents=True, exist_ok=True)
    out = gdir / f"{sha}.review.md"
    out.write_text(render(verdict, sha, result, a.report.read_text(encoding="utf-8"), a.session),
                   encoding="utf-8")
    a.log_dir.mkdir(parents=True, exist_ok=True)
    with (a.log_dir / f"{repo_name(repo)}.tsv").open("a", encoding="utf-8") as fh:
        fh.write("\n".join(log_rows(result, sha, verdict)) + "\n")
    print(f"**Review: {verdict}** · {sha[:7]} — wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
