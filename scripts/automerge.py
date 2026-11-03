#!/usr/bin/env python3
"""Merge a PR without the user when the facts hold and a fresh Claude, the merge check, finds nothing for the user
to look at. Report to Slack only the PRs that need the user.

Run by /pr after CI, or by the merge poller (scripts/merge_poll.py) once CI has finished:
`python3 ~/projects/hhmode/scripts/automerge.py <PR number>` from the task worktree.

0. One run per PR at a time: an exclusive lock on <git common dir>/gate/merge-<owner>-<repo>-<n>.lock is held for the
   whole run, and the PR is read fresh after taking it. A PR that is no longer open ends the run quietly (printed, no
   Slack). The runner workflow and /pr step 8 could start two merge checks on one PR, each with its own Claude (verifier
   on k-defense-kg caf3607, P1).
1. Facts, checked here for the PR's head commit. Any that fails stops the merge, and the merge check never starts:
  - the verifier's record says Review PASS and verify PASS (gate/<sha>.review.md, written by record_review.py);
  - the Codex review exists (gate/<sha>.gpt.md, copied by verify_fresh.sh). A standard review (and an old `full` one)
    needs its own. A fix or carry record, which ran without Codex or took an earlier review's result, is exempt, but
    the chain of `since` records must still hold one Codex review;
  - neither the verifier nor Codex rated the risk high (references/tiers.md); a re-review scoped `since` an
    earlier commit also counts that commit's tiers. The author's tier in the PR body is not read: it is free text,
    and the author is the one who wants the merge;
  - GitHub says the PR is open into main and mergeable, and no check is failing or still running;
  - the PR body fills the PR form and names every acceptance criterion of the issues it closes (scripts/forms.py);
  - where the repo uses the Codex app on GitHub, its security review of this PR has finished with no unresolved
    findings (codex_review below). It edits one PR comment that carries its state as JSON; that JSON is read, not the
    prose around it.
2. The merge check: a fresh headless Claude that wrote and verified nothing reads the PR, the issues it closes, the
   repo's CLAUDE.md, the records, the Codex app's comments and the diff (skills/code-review/merge-check.md) and answers
   merge or not, with a reason. A repo rule that sends this kind of change to the user wins over the tiers above.
3. On a yes, Claude runs the merge itself (user decision 2026-11-02): it is allowed exactly one command, `gh pr merge
   <n> -R <owner>/<repo> --squash --match-head-commit <reviewed sha>`, and nothing else. An exact allowlist entry pins
   the PR and the commit (measured 2026-11-02: the entry for PR 17 ran, the same command for PR 16 was denied), so a
   push after the review cannot ride along (pstack: only a clean verdict on the patch that merges authorizes it). The
   script then reads the PR back: merged means Claude's command ran; still open means it did not (a denied tool), and
   the script runs the same pinned command itself, so an approved PR is never left unmerged. Then each issue the PR
   closes is closed if GitHub left it open, and the merge check's reason goes on the PR as a comment. Only in mode `on`
   and not --dry-run does Claude get the command; otherwise the check runs with no tools.

Slack, only for what needs the user (user decision 2026-10-30): a high tier, a merge check that says no, a failed
merge or issue close, unresolved Codex findings, or --report (the author gives up after three rounds). A reason the
author fixes (CI, review, a conflict, the PR form) is printed, not sent. The same message for the same PR head is sent
once (a marker file in the gate dir): CI and Gate both finishing starts the runner twice per push (verifier on
k-defense-kg caf3607: a high-tier PR got "Needs you" twice). Mode, from local/automerge (gitignored): `on` merges;
anything else reports what it would have done, to Slack. Slack target: local/notify.json {"token_file": "...",
"channel": "..."}; without it the message is printed. --dry-run prints the facts and does nothing else (no merge
check); it still reads the issues the PR closes and the Codex app's state, which is read-only. Every message is plain
English (user decision 2026-10-30).
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

from forms import check_pr, tier_line

HERE = pathlib.Path(__file__).resolve().parent.parent          # hhmode root
ORDER = {"low": 0, "medium": 1, "high": 2}
UNKNOWN = "unknown"                 # merged, but the merge commit could not be read back
MAX_AUTO = "medium"                 # the highest tier that merges without the user (user decision 2026-10-30)
LIGHT = ("fix", "carry")            # records that need no Codex review of their own (review_weight.py)
VERDICT_WORDS = {"PASS": "passed", "ISSUES": "found issues", "BLOCKED": "could not run", "FAIL": "failed"}
HEAD_RE = re.compile(r"^\*\*Review: (\w+)\*\* · ([0-9a-f]{7,40}) · (\w+)(?: · since ([0-9a-f]{7,40}))?")


def gpt_tier(text: str) -> str | None:
    """The tier on the line after `## Tier`, only in the exact form `<tier> — <reason>`; anything else reads as none
    and the merge stops. Reading tier words out of free text kept finding a lower tier than written ("medium - high",
    "medium – high", "**medium** - **high**": verifier on a93fe87, 8ddbe0d, c982ba2)."""
    m = re.search(r"^## Tier\s*\n+(.*)$", text or "", re.M | re.I)
    return tier_line(m.group(1)) if m else None


def record_fields(text: str) -> dict:
    head = HEAD_RE.match(text or "")
    # The last comment is the record's own; a report may quote an older one (record_review.render escapes them now).
    metas = list(re.finditer(r"<!-- verifier-session: [^;]+; verify: (\w+); (?:tier: (\w+); )?lanes:", text or ""))
    meta = metas[-1] if metas else None
    return {"review": head.group(1) if head else None, "since": head.group(4) if head else None,
            "mode": head.group(3) if head else None,
            "verify": meta.group(1) if meta else None, "tier": meta.group(2) if meta else None}


def checks_state(rollup: list) -> str:
    """`none` (no checks; hhmode has no CI), `ok`, `pending` or `failing` for GitHub's statusCheckRollup."""
    if not rollup:
        return "none"
    state = "ok"
    for c in rollup:
        status = (c.get("status") or "").upper()
        concl = (c.get("conclusion") or c.get("state") or "").upper()
        if concl in {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"}:
            return "failing"
        if status in {"QUEUED", "IN_PROGRESS", "PENDING", "WAITING"} or concl in {"PENDING", "EXPECTED", ""}:
            state = "pending"
    return state


def decide(pr: dict, records: list[dict]) -> tuple[bool, list[str], dict, dict]:
    """Pure. `records`: the head commit's first, then each `since` ancestor's, each {review, mode, verify, tier, gpt}.
    Returns (merge, reasons it may not, tiers seen, state of each check), worded for the user."""
    reasons, head = [], records[0]
    status = {"review": VERDICT_WORDS.get(head["review"], head["review"] or "no record"),
              "verify": VERDICT_WORDS.get(head["verify"], head["verify"] or "no record"),
              "ci": checks_state(pr.get("statusCheckRollup")), "mergeable": pr.get("mergeable")}
    if pr.get("state") != "OPEN":
        reasons.append(f"the PR is not open ({pr.get('state')})")
    if pr.get("baseRefName") != "main":
        # The verifier reviews `origin/main...HEAD`; into another base the merge would carry changes nobody reviewed
        # (GPT lane, 2026-10-29).
        reasons.append(f"the PR merges into {pr.get('baseRefName')}, not main, and the review is against main")
    if head["review"] != "PASS":
        reasons.append(f"review: {status['review']}")
    if head["verify"] != "PASS":
        reasons.append(f"tests: {status['verify']}")
    # The author's tier in the PR body is for the reader, not the decision: it is free text, and the author is the
    # one who wants the merge (pstack). The verifier and Codex rate the change independently, in fixed forms.
    tiers = {}
    no_codex = "the Codex review did not run for this verification{}, or its risk tier could not be read"
    for i, r in enumerate(records):
        tag = "" if i == 0 else f" ({r.get('sha', '')[:7]})"
        light = r.get("mode") in LIGHT
        tiers[f"Claude verifier{tag}"] = r["tier"]
        if r["gpt"] is not None or not light:
            tiers[f"Codex review{tag}"] = r["gpt"]
        if r["tier"] is None:
            reasons.append(f"no Claude verifier record{tag}" if r["review"] is None
                           else f"the Claude verifier record{tag} has no risk tier (written before the field existed)")
        if r["gpt"] is None and not light:
            reasons.append(no_codex.format(tag))
    # Fix and carry records are exempt one by one, but a chain made only of them has no Codex review at all.
    if all(r.get("mode") in LIGHT and r["gpt"] is None for r in records):
        reasons.append(no_codex.format(""))
    top = max((v for v in tiers.values() if v in ORDER), key=ORDER.get, default=None)
    if top and ORDER[top] > ORDER[MAX_AUTO]:
        reasons.append(f"risk tier {top}")
    if pr.get("mergeable") != "MERGEABLE":
        reasons.append(f"the PR cannot be merged yet ({pr.get('mergeable')})")
    if status["ci"] in {"pending", "failing"}:
        reasons.append({"failing": "CI is failing", "pending": "CI is still running"}[status["ci"]])
    return (not reasons, reasons, tiers, status)


def form_problems(pr: dict, issues: list[dict]) -> list[str]:
    """Where the PR body does not fill the PR form or leaves out a criterion of an issue it closes (scripts/forms.py),
    worded as reasons for the author to fix. Not for the user: nothing here is a judgement call."""
    return [f"PR body: {p}" for p in check_pr(pr.get("body") or "", {i["number"]: i.get("body") or "" for i in issues})]


def gh(*args: str, cwd: pathlib.Path) -> str:
    return subprocess.run(["gh", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def load_records(gate: pathlib.Path, sha: str) -> list[dict]:
    out, seen = [], set()
    while sha and sha not in seen:
        seen.add(sha)
        rec = next(iter(sorted(gate.glob(f"{sha}*.review.md"))), None)
        gpt = next(iter(sorted(gate.glob(f"{sha}*.gpt.md"))), None)
        f = record_fields(rec.read_text(encoding="utf-8")) if rec else {"review": None, "verify": None, "mode": None,
                                                                       "tier": None, "since": None}
        f["text"] = rec.read_text(encoding="utf-8") if rec else ""
        f["gpt_text"] = gpt.read_text(encoding="utf-8") if gpt else ""
        f["gpt"] = gpt_tier(f["gpt_text"]) if gpt else None
        f["sha"] = rec.name.split(".")[0] if rec else sha
        out.append(f)
        sha = f["since"]
    return out


ISSUES_QUERY = ("query($o:String!,$r:String!,$n:Int!){repository(owner:$o,name:$r){pullRequest(number:$n)"
                "{closingIssuesReferences(first:20){nodes{number url state title body}}}}}")


def owner_repo(pr: dict) -> tuple[str, str]:
    return re.search(r"github\.com/([^/]+)/([^/]+)/pull/", pr["url"]).groups()


def closing_issues(pr: dict, cwd) -> list[dict]:
    """The issues this PR closes on merge (`Closes #n` in its body, or linked by hand), from GitHub's GraphQL API."""
    o, r = owner_repo(pr)
    out = gh("api", "graphql", "-f", f"query={ISSUES_QUERY}", "-F", f"o={o}", "-F", f"r={r}",
             "-F", f"n={pr['number']}", cwd=cwd)
    return json.loads(out)["data"]["repository"]["pullRequest"]["closingIssuesReferences"]["nodes"]


CODEX_BOT = "chatgpt-codex-connector[bot]"     # the Codex app's login in the REST API; gh prints it without "[bot]"
CODEX_MARK = "codex-review-state:v1"
CODEX_STATE = re.compile(r"<!--\s*" + re.escape(CODEX_MARK) + r"\s+(\{.*?\})\s*-->", re.S)
CODEX_RECENT = 10       # recent PRs read to tell whether the repo uses the Codex app


def rest_list(path: str, cwd) -> list[dict]:
    """Every item of a REST list endpoint, all pages."""
    return [item for page in json.loads(gh("api", path, "--paginate", "--slurp", cwd=cwd)) for item in page]


def from_codex(items: list[dict]) -> list[dict]:
    """The comments written by the Codex app. Only its own login counts: anyone can paste the marker into a comment,
    and a REST `Bot` login ends in "[bot]", which a person's cannot."""
    return [c for c in items if (c.get("user") or {}).get("login") == CODEX_BOT]


def codex_state(comments: list[dict]) -> dict | None:
    """The Codex app's review state: the JSON inside `<!-- codex-review-state:v1 {...} -->` in its newest PR comment,
    never the prose around it. None when it has left no such comment on this PR, {} when the JSON cannot be read."""
    for c in reversed(from_codex(comments)):
        m = CODEX_STATE.search(c.get("body") or "")
        if m:
            try:
                state = json.loads(m.group(1))
            except ValueError:
                return {}
            return state if isinstance(state, dict) else {}
    return None


def codex_reasons(state: dict | None, head: str) -> tuple[list[str], bool, str | None]:
    """(reasons it may not merge, whether they are for the user, a note for the merge check) from the app's state.
    Not finished is the author's to wait out (the merge poller looks again on its next pass); unresolved
    findings are for the user. A review of an earlier commit than the head still counts, with the note."""
    sec = (state or {}).get("security_review")
    sec = sec if isinstance(sec, dict) else {}
    if sec.get("status") != "completed":
        return ["the Codex security review has not finished"], False, None
    if sec.get("has_unresolved_findings") is True:
        return ["the Codex security review has unresolved findings"], True, None
    seen = sec.get("commit_sha")
    if seen == head:
        return [], False, None
    return [], False, (f"The Codex security review covered commit {str(seen)[:7] if seen else 'unknown'}, "
                       f"not this PR's head {head[:7]}.")


def codex_review(pr: dict, cwd) -> tuple[list[str], bool, str]:
    """(reasons it may not merge, whether they are for the user, text for the merge check) from the Codex app. The repo
    uses the app when this PR or any of its CODEX_RECENT most recent PRs has a comment containing the marker, so there
    is no list of repos to keep. Nothing for a repo that does not."""
    o, r = owner_repo(pr)
    n = pr["number"]
    issue_comments = rest_list(f"repos/{o}/{r}/issues/{n}/comments", cwd)
    # Only the app's own comments say the repo uses it: a marker anyone pasted would make every PR wait for a review
    # no app will write (verifier and Codex on f97c493). `gh pr list` drops the "[bot]" suffix, so the recent PRs'
    # comments are read through REST, where the login tells the app from a person.
    uses = any(CODEX_MARK in (c.get("body") or "") for c in from_codex(issue_comments))
    if not uses:
        recent = json.loads(gh("pr", "list", "-R", f"{o}/{r}", "--state", "all", "--limit", str(CODEX_RECENT),
                               "--json", "number", cwd=cwd))
        uses = any(CODEX_MARK in (c.get("body") or "") for q in recent if q["number"] != n
                   for c in from_codex(rest_list(f"repos/{o}/{r}/issues/{q['number']}/comments", cwd)))
    if not uses:
        return [], False, ""
    reasons, for_user, note = codex_reasons(codex_state(issue_comments), pr["headRefOid"])
    reviews = from_codex(rest_list(f"repos/{o}/{r}/pulls/{n}/reviews", cwd))
    lines = from_codex(rest_list(f"repos/{o}/{r}/pulls/{n}/comments", cwd))
    texts = [c["body"] for c in from_codex(issue_comments)] + [c["body"] for c in reviews if c.get("body")]
    texts += [f"{c['path']}:{c.get('line') or c.get('original_line') or '?'}: {c['body']}" for c in lines]
    section = [f"# Codex security review on GitHub (the Codex app, {CODEX_BOT})"] + ([note] if note else [])
    section += ["Its comments on this PR (comments, review bodies, then review line comments):"]
    return reasons, for_user, "\n\n".join(section + (texts or ["(none)"]))


DIFF_CAP = 300_000      # characters of diff the merge check reads; a bigger PR goes to the user (GPT lane on c470756:
                        # a change past a cut could not be named, so it would pass)
CLOSE_WAIT = 5          # seconds to let GitHub's own auto-close land before closing an issue ourselves
CHECK_SCHEMA = {"type": "object", "properties": {"merge": {"type": "boolean"}, "reason": {"type": "string"}},
                "required": ["merge", "reason"], "additionalProperties": False}


def repo_rules(pr: dict, cwd) -> str | None:
    """The repo's CLAUDE.md on the PR's base branch as GitHub has it now, "" when there is none, None when it could
    not be read. Its merge rules outrank this script's defaults: k-defense-kg's section 4 sends medium to the user
    (merge check on k-defense-kg #51, 2026-10-30). Not a local ref, which may predate a new rule (GPT lane on
    c470756); an unreadable file is not an absent one, so the caller sends the PR to the user."""
    o, r = owner_repo(pr)
    try:
        return gh("api", "-H", "Accept: application/vnd.github.raw",
                  f"repos/{o}/{r}/contents/CLAUDE.md?ref={pr['baseRefName']}", cwd=cwd)
    except subprocess.CalledProcessError as e:
        return "" if "HTTP 404" in (e.stderr or "") else None


def check_input(pr: dict, issues: list[dict], records: list[dict], diff: str, rules: str = "",
                codex: str = "") -> str:
    parts = [f"# PR #{pr['number']}: {pr['title']}\n\n{pr.get('body') or '(no body)'}"]
    if rules:
        parts.append(f"# The repo's CLAUDE.md (main)\n\n{rules}")
    parts += [f"# Issue #{i['number']}, which this PR closes: {i['title']}\n\n{i.get('body') or '(no body)'}"
              for i in issues]
    for r in records:
        parts.append(f"# Verifier record, {r['sha'][:7]}\n\n{r.get('text') or '(none)'}")
        parts.append(f"# Codex review, {r['sha'][:7]}\n\n{r.get('gpt_text') or '(none)'}")
    if codex:
        parts.append(codex)
    parts.append(f"# Diff\n\n```diff\n{diff}\n```")
    return "\n\n".join(parts)


def merge_args(pr: dict) -> list[str]:
    """The one `gh` call that merges this PR: pinned to the repo, the PR and the reviewed commit."""
    o, r = owner_repo(pr)
    return ["pr", "merge", str(pr["number"]), "-R", f"{o}/{r}", "--squash", "--match-head-commit", pr["headRefOid"]]


def merge_command(pr: dict) -> str:
    return " ".join(["gh", *merge_args(pr)])


def merge_check(text: str, command: str | None = None) -> dict:
    """{"merge", "reason", "session"} from a fresh headless Claude, in an empty folder with every customization off
    (--safe-mode): run inside the PR's worktree it also read the PR branch's own CLAUDE.md, so a PR could rewrite the
    rule it is judged by (verifier on c470756). With no `command` it has no tools. With one it has Bash and is allowed
    exactly that command: an exact entry in --allowedTools pins the PR and the commit (user decision 2026-11-02;
    measured: the entry for PR 17 ran, the same command for PR 16 was denied). One that cannot answer is a no: the PR
    goes to the user with what it said."""
    prompt = "Decide whether this pull request merges without the user. The input is on stdin."
    tools = ["--tools", ""]
    if command:
        prompt += f" If your answer is yes, run this command once, exactly as written, and then answer: {command}"
        tools = ["--tools", "Bash", "--allowedTools", f"Bash({command})"]
    cmd = ["claude", "-p", prompt,
           "--safe-mode", "--model", os.environ.get("MERGE_CHECK_MODEL", "claude-opus-5-5"),
           "--append-system-prompt-file", str(HERE / "skills" / "code-review" / "merge-check.md"),
           *tools, "--output-format", "json", "--json-schema", json.dumps(CHECK_SCHEMA)]

    def no(why: str) -> dict:
        return {"merge": False, "reason": f"the merge check could not answer: {why.strip()[:300]}", "session": ""}
    try:
        with tempfile.TemporaryDirectory(prefix="merge-check-") as d:      # removed when the check is done
            run = subprocess.run(cmd, input=text, cwd=d, capture_output=True, text=True, timeout=900)
    except (subprocess.SubprocessError, OSError) as e:
        return no(str(e))
    try:
        d = json.loads(run.stdout)
    except ValueError:
        return no(run.stderr or run.stdout or f"exit {run.returncode}")
    ans = d.get("structured_output") or {}
    if isinstance(ans.get("merge"), bool) and str(ans.get("reason", "")).strip():
        return {"merge": ans["merge"], "reason": ans["reason"].strip(), "session": d.get("session_id", "")}
    return no(str(d.get("result") or run.stderr or "its answer was empty"))


def close_issues(issues: list[dict], pr: dict, merged: str, cwd) -> list[str]:
    """Close each issue the PR closes that GitHub left open. GitHub closes them itself a moment after the merge, so
    wait once before looking. Returns the ones that failed, for the user."""
    if issues:
        time.sleep(CLOSE_WAIT)
    by = f"the merge of #{pr['number']}" + (f" ({merged[:7]})" if merged and merged != UNKNOWN else "")
    failed = []
    for i in issues:
        try:
            if json.loads(gh("issue", "view", i["url"], "--json", "state", cwd=cwd))["state"] != "CLOSED":
                gh("issue", "close", i["url"], "--reason", "completed", "--comment", f"Done in {by}", cwd=cwd)
        except subprocess.CalledProcessError as e:
            failed.append(f"could not close issue #{i['number']}: {(e.stderr or str(e)).strip()[:200]}")
    return failed


BY_CLAUDE = "the merge check (Claude)"
BY_SCRIPT = "this script, because the merge check's own command did not run"


def merge_state(number: int, cwd) -> tuple[str, str | None]:
    """(state, merge commit) of the PR as GitHub has it now."""
    d = json.loads(gh("pr", "view", str(number), "--json", "state,mergeCommit", cwd=cwd))
    return d["state"], (d.get("mergeCommit") or {}).get("oid")


def finish_merge(pr: dict, cwd) -> tuple[str | None, str | None, str | None]:
    """After a yes from a merge check that held the merge command: read the PR back. Merged means Claude's command ran.
    Still open means it did not (a denied tool, or it skipped the command), so the script runs the same pinned command
    itself and an approved PR is never left unmerged. Returns (merge commit, who merged, error). A merge refused by
    branch protection, a draft or a push after the review is an error to report, not to stop on silently (verifier note
    on 08df90d); one that went through but could not be read back is not an error (verifier note on f07e72f)."""
    try:
        state, oid = merge_state(pr["number"], cwd)
    except (subprocess.CalledProcessError, KeyError, ValueError) as e:
        return None, None, ("could not read the PR after the merge check, so it is not known whether it merged: "
                            + (getattr(e, "stderr", None) or str(e)).strip()[:200])
    if state == "MERGED":
        return oid or UNKNOWN, BY_CLAUDE, None
    if state != "OPEN":
        return None, None, f"the PR was {state.lower()} while the merge check ran"
    try:
        gh(*merge_args(pr), cwd=cwd)
    except subprocess.CalledProcessError as e:
        return None, None, ((e.stderr or "").strip().splitlines() or [str(e)])[-1][:300]
    try:
        oid = merge_state(pr["number"], cwd)[1]
    except (subprocess.CalledProcessError, KeyError, ValueError):
        oid = None
    return oid or UNKNOWN, BY_SCRIPT, None


CI_WORDS = {"none": "none", "ok": "passing", "pending": "running", "failing": "failing"}
MERGEABLE_WORDS = {"MERGEABLE": "no conflicts", "CONFLICTING": "conflicts", "UNKNOWN": "still checking"}


# A mark in front of a message the user should tell apart at a glance in Slack (user, 2026-11-02, hhmode #23): one
# they act on, one that failed, one that merged. post_once compares messages without it.
MARKS = {"Needs you": "🔔 ", "Merge failed": "⚠️ ", "Merged": "✅ "}


def slack_key(text: str) -> str:
    """What post_once compares: the first line without its mark, so a message sent before the marks existed is not
    taken for a new one."""
    first = text.split("\n", 1)[0]
    for mark in MARKS.values():
        first = first.removeprefix(mark)
    return first


def message(pr: dict, merge: bool, reasons: list[str], tiers: dict, status: dict, mode: str,
            merged_sha: str | None, error: str | None = None, check: dict | None = None,
            problems: list[str] | None = None, merged_by: str | None = None,
            closed: list[int] | None = None) -> str:
    m = re.search(r"github\.com/[^/]+/([^/]+)/pull/", pr.get("url", ""))
    repo = m.group(1) if m else "?"
    if error:
        head = "Merge failed"
    elif merge and merged_sha:
        head = "Merged"
    elif merge:
        head = ("[dry-run]" if mode == "dry-run" else "[trial]") + " would merge, not merged"
    else:
        head = "Needs you"
    lines = [f"{MARKS.get(head, '')}*[{repo} #{pr['number']}] {head}* — {pr['title']}",
             f"• Review {status['review']} · Tests {status['verify']} · CI {CI_WORDS.get(status['ci'], status['ci'])}"
             f" · {MERGEABLE_WORDS.get(status['mergeable'], status['mergeable'])}",
             "• Risk (any \"high\" needs you): " + " · ".join(f"{k} {v or 'none'}" for k, v in tiers.items())]
    if error:
        lines.append(f"• The merge did not go through: {error}")
    elif merged_sha == UNKNOWN:
        lines.append("• Merged, but the merge commit could not be read back. To undo it, use Revert on the PR page")
    elif merged_sha:
        lines.append(f"• To undo: `git revert {merged_sha[:7]}` or Revert on the PR page")
    elif not merge:
        lines.append("• Why it was not merged: " + ", ".join(reasons))
    if merged_sha and merged_by:
        lines.append(f"• Merged by {merged_by}")
    if merged_sha and closed:
        lines.append("• Closed: " + ", ".join(f"#{n}" for n in closed))
    if check and check["merge"]:
        lines.append(f"• Merge check (Claude): {check['reason']}")
    lines += [f"• {p}" for p in problems or []]
    return "\n".join(lines + [pr["url"]])


def post_slack(text: str) -> str:
    cfg_path = HERE / "local" / "notify.json"
    if not cfg_path.exists():
        return "not sent: no local/notify.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    token = pathlib.Path(cfg["token_file"]).expanduser().read_text().strip()
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=json.dumps({"channel": cfg["channel"], "text": text}).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"})
    r = json.load(urllib.request.urlopen(req, timeout=30))
    return "sent" if r.get("ok") else f"not sent: {r.get('error')}"


def post_once(text: str, gate: pathlib.Path, number: int, head: str) -> str:
    """post_slack, but the same message for the same PR head goes out once. The marker file `slack-<n>-<sha>.sent`
    holds a hash of each message sent for that head. CI and Gate both finishing starts the runner twice per push
    (verifier on k-defense-kg caf3607: a high-tier PR got "Needs you" twice). A message that did not go out is not
    marked. Only the first line counts (the PR and the outcome): the merge check's reason is Claude's prose, which
    differs from run to run, so hashing the whole message sent the same "Needs you" twice."""
    marker = gate / f"slack-{number}-{head}.sent"
    digest = hashlib.sha256(slack_key(text).encode("utf-8")).hexdigest()
    if marker.exists() and digest in marker.read_text().split():
        return "not sent: the same message was already sent for this commit"
    sent = post_slack(text)
    if sent == "sent":
        gate.mkdir(parents=True, exist_ok=True)
        with marker.open("a") as f:
            f.write(digest + "\n")
    return sent


def decision_file(gate: pathlib.Path, number: int, head: str) -> pathlib.Path:
    return gate / f"merge-check-{number}-{head}.json"


def record_decision(gate: pathlib.Path, number: int, head: str, check: dict) -> None:
    """The merge check's answer for this head, kept whether or not its Slack message goes out: the merge poller and a
    second run of this script read it instead of asking Claude again (hhmode #26)."""
    gate.mkdir(parents=True, exist_ok=True)
    decision_file(gate, number, head).write_text(json.dumps(check), encoding="utf-8")


def decided(gate: pathlib.Path, number: int, head: str) -> dict | None:
    f = decision_file(gate, number, head)
    try:
        d = json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
    except ValueError:
        return None
    return d if isinstance(d, dict) and isinstance(d.get("merge"), bool) else None


@contextlib.contextmanager
def merge_lock(gate: pathlib.Path, owner: str, repo: str, number: int):
    """One merge check per PR at a time: an exclusive lock on <gate>/merge-<owner>-<repo>-<n>.lock, held for the whole
    run. A second run waits for the first (verifier on k-defense-kg caf3607, P1: the runner and /pr step 8 started two
    merge checks on one PR at once, each with its own Claude). The lock goes when the file closes, also on a crash."""
    gate.mkdir(parents=True, exist_ok=True)
    with open(gate / f"merge-{owner}-{repo}-{number}.lock", "a") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"automerge: another merge check is running on #{number}; waiting for it")
            fcntl.flock(f, fcntl.LOCK_EX)
        yield


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("pr", type=int)
    ap.add_argument("--repo", type=pathlib.Path, default=pathlib.Path.cwd())
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", action="store_true",
                    help="send to Slack even a reason the author could fix (/pr step 9, after three rounds)")
    a = ap.parse_args(argv)

    repo = a.repo.resolve()
    common = subprocess.run(["git", "-C", str(repo), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            check=True, capture_output=True, text=True).stdout.strip()
    gate = pathlib.Path(common) / "gate"
    owner, name = owner_repo(json.loads(gh("pr", "view", str(a.pr), "--json", "url", cwd=repo)))
    with merge_lock(gate, owner, name, a.pr):
        return run(a, repo, gate)


def run(a: argparse.Namespace, repo: pathlib.Path, gate: pathlib.Path) -> int:
    # Read after taking the lock: a run that waited may find the PR merged by the one before it.
    pr = json.loads(gh("pr", "view", str(a.pr), "--json",
                       "number,title,url,state,baseRefName,headRefOid,body,mergeable,statusCheckRollup", cwd=repo))
    if pr["state"] != "OPEN":
        print(f"automerge: #{a.pr} is {pr['state']}, nothing to do")
        return 0
    records = load_records(gate, pr["headRefOid"])
    merge, reasons, tiers, status = decide(pr, records)
    for_user = "high" in tiers.values()     # the user's call; every other reason is the author's to fix
    mode_file = HERE / "local" / "automerge"
    mode = mode_file.read_text().strip() if mode_file.exists() else "shadow"

    # The issues the PR closes are read before deciding, also in --dry-run (read-only): the PR form is a fact like CI.
    # One that cannot be read sends the PR to the user, with the reason, instead of passing unchecked.
    try:
        issues = closing_issues(pr, repo)
        reasons += form_problems(pr, issues)
    except subprocess.CalledProcessError as e:
        issues = []
        reasons.append(f"could not read the issues this PR closes: {(e.stderr or str(e)).strip()[:200]}")
        for_user = True
    # The Codex app's review is a fact too, read the same way (read-only, also in --dry-run).
    codex_text = ""
    try:
        c_reasons, codex_user, codex_text = codex_review(pr, repo)
        reasons += c_reasons
        for_user = for_user or codex_user
    except subprocess.CalledProcessError as e:
        reasons.append(f"could not read the Codex review from GitHub: {(e.stderr or str(e)).strip()[:200]}")
        for_user = True
    merge = not reasons

    check = merged_anyway = None
    if merge and not a.dry_run:
        # Anything the check cannot read sends the PR to the user, with the reason, instead of crashing silently
        # after the facts passed (verifier on c470756).
        try:
            diff = gh("pr", "diff", str(a.pr), cwd=repo)
            rules = repo_rules(pr, repo)
            unread = ("could not read the repo's CLAUDE.md" if rules is None
                      else f"the change is too big ({len(diff)} characters) for the merge check to read all of it"
                      if len(diff) > DIFF_CAP else None)
        except subprocess.CalledProcessError as e:
            unread = f"could not read what the merge check needs from GitHub: {(e.stderr or str(e)).strip()[:200]}"
        if unread:
            merge, for_user = False, True
            reasons.append(unread)
        else:
            # Claude gets the merge command only when this run is allowed to merge: mode `on`, not --dry-run.
            held = merge_command(pr) if mode == "on" else None
            earlier = decided(gate, pr["number"], pr["headRefOid"]) if mode == "on" else None
            if earlier:
                # This head was judged already: another starter (/pr step 8 or the poller) does not ask again, and a no
                # stays a no whether or not its DM went out (verifier on 91848ab, two P1: a no whose Slack failed was
                # judged again every pass; the second of two starters judged a head the first had sent to the user).
                # A yes the merge did not follow (an error) is retried with the same pinned command, no new judgment.
                check, held = earlier, None
                print(f"automerge: the merge check already said {'yes' if check['merge'] else 'no'} for "
                      f"{pr['headRefOid'][:7]}; not asking again")
            else:
                check = merge_check(check_input(pr, issues, records, diff, rules, codex_text), held)
                # Only an answer Claude gave is kept: a timeout or a missing answer (no session) is asked again next
                # run, not frozen as a no for this head (merge check and verifier note on PR #27).
                if mode == "on" and check.get("session"):
                    record_decision(gate, pr["number"], pr["headRefOid"], check)
            if not check["merge"]:
                merge, for_user = False, True
                reasons.append(f"Merge check (Claude): {check['reason']}")
                if held:
                    # Claude held the merge command, so it may have run it and then lost its answer (a timeout, no
                    # structured output) or said no: the PR is read back whatever the answer (verifier and Codex on
                    # f97c493, P1: a merge that happened was reported as not merged, and its issue left open).
                    try:
                        state, oid = merge_state(pr["number"], repo)
                    except (subprocess.CalledProcessError, KeyError, ValueError):
                        state, oid = None, None
                    if state == "MERGED":
                        merged_anyway = oid or UNKNOWN

    merged_sha = merged_by = error = None
    problems: list[str] = []
    if merged_anyway:
        merge, merged_sha, merged_by = True, merged_anyway, BY_CLAUDE
        problems.append("the merge check's command merged the PR, but its answer was lost or said no: "
                        f"{check['reason']}")
        problems += close_issues(issues, pr, merged_sha, repo)
    elif merge and mode == "on" and not a.dry_run:
        merged_sha, merged_by, error = finish_merge(pr, repo)
        if merged_sha:
            problems = close_issues(issues, pr, merged_sha, repo)
            said = ("merged." if merged_by == BY_CLAUDE else "approved the merge, but its merge command did not run, "
                    "so the script ran the same command and merged the PR.")
            try:
                gh("pr", "comment", str(a.pr), "--body",
                   f"Merge check (Claude, session {check['session'][:8]}): {said} {check['reason']}", cwd=repo)
            except subprocess.CalledProcessError as e:
                problems.append(f"could not comment the merge check on the PR: {(e.stderr or str(e)).strip()[:200]}")
    text = message(pr, merge, reasons, tiers, status, "dry-run" if a.dry_run else mode, merged_sha, error,
                   check, problems, merged_by,
                   # only the issues that did close: a failed close is listed among the problems instead (verifier
                   # note on 502f5a8)
                   [i["number"] for i in issues if not any(p.startswith(f"could not close issue #{i['number']}:")
                                                           for p in problems)] if merged_sha else None)
    print(text)
    # A merge is reported too (user, 2026-11-02, hhmode #18): until then a merge in mode `on` sent nothing, so the
    # user heard of no merge at all. Still once per PR head (post_once).
    if not a.dry_run and (merged_sha or for_user or a.report or error or problems or mode != "on"):
        try:
            print(f"[slack] {post_once(text, gate, a.pr, pr['headRefOid'])}")
        except Exception as e:                          # after a merge, a Slack failure must not hide it
            print(f"[slack] not sent: {e}")
    shown = "dry-run" if a.dry_run else mode
    verdict = ("MERGE FAILED" if error else "MERGED" if merged_sha
               else f"WOULD MERGE ({shown}, not merged)" if merge else "TO USER")
    print(f"automerge: {verdict} · #{a.pr} · {pr['headRefOid'][:7]} · mode {mode}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
