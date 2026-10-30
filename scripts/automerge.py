#!/usr/bin/env python3
"""Merge a PR without the user when the facts hold and a fresh Claude, the merge check, finds nothing for the user
to look at. Report to Slack only the PRs that need the user.

Run by /pr after CI: `python3 ~/projects/hhmode/scripts/automerge.py <PR number>` from the task worktree.

1. Facts, checked here for the PR's head commit. Any that fails stops the merge, and the merge check never starts:
  - the verifier's record says Review PASS and verify PASS (gate/<sha>.review.md, written by record_review.py);
  - the Codex review exists (gate/<sha>.gpt.md, copied by verify_fresh.sh);
  - neither the verifier nor Codex rated the risk high (references/tiers.md); a re-review scoped `since` an
    earlier commit also counts that commit's tiers. The author's tier in the PR body is not read: it is free text,
    and the author is the one who wants the merge;
  - GitHub says the PR is open into main and mergeable, and no check is failing or still running;
  - the PR body fills the PR form and names every acceptance criterion of the issues it closes (scripts/forms.py).
2. The merge check: a fresh headless Claude that wrote and verified nothing reads the PR, the issues it closes, the
   repo's CLAUDE.md, the records and the diff (skills/code-review/merge-check.md) and answers merge or not, with a
   reason. A repo rule that sends this kind of change to the user wins over the tiers above.
3. The merge pins the reviewed commit (--match-head-commit), so a push after the review cannot ride along (pstack:
   only a clean verdict on the patch that merges authorizes it). Then each issue the PR closes is closed if GitHub
   left it open, and the merge check's reason goes on the PR as a comment.

Slack, only for what needs the user (user decision 2026-10-30): a high tier, a merge check that says no, a failed
merge or issue close, or --report (the author gives up after three rounds). A reason the author fixes (CI, review,
a conflict, the PR form) is printed, not sent. Mode, from local/automerge (gitignored): `on` merges; anything else
reports what it would have done, to Slack. Slack target: local/notify.json {"token_file": "...", "channel": "..."};
without it the message is printed. --dry-run prints the facts and does nothing else (no merge check); it still reads
the issues the PR closes, which is read-only. Every message is plain English (user decision 2026-10-30).
"""
from __future__ import annotations

import argparse
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
    meta = re.search(r"<!-- verifier-session: [^;]+; verify: (\w+); (?:tier: (\w+); )?lanes:", text or "")
    return {"review": head.group(1) if head else None, "since": head.group(4) if head else None,
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
    """Pure. `records`: the head commit's first, then each `since` ancestor's, each {review, verify, tier, gpt}.
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
    for i, r in enumerate(records):
        tag = "" if i == 0 else f" ({r.get('sha', '')[:7]})"
        tiers[f"Claude verifier{tag}"] = r["tier"]
        tiers[f"Codex review{tag}"] = r["gpt"]
        if r["tier"] is None:
            reasons.append(f"no Claude verifier record{tag}" if r["review"] is None
                           else f"the Claude verifier record{tag} has no risk tier (written before the field existed)")
        if r["gpt"] is None:
            reasons.append(f"the Codex review did not run for this verification{tag}, or its risk tier "
                           "could not be read")
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
        f = record_fields(rec.read_text(encoding="utf-8")) if rec else {"review": None, "verify": None,
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


def check_input(pr: dict, issues: list[dict], records: list[dict], diff: str, rules: str = "") -> str:
    parts = [f"# PR #{pr['number']}: {pr['title']}\n\n{pr.get('body') or '(no body)'}"]
    if rules:
        parts.append(f"# The repo's CLAUDE.md (main)\n\n{rules}")
    parts += [f"# Issue #{i['number']}, which this PR closes: {i['title']}\n\n{i.get('body') or '(no body)'}"
              for i in issues]
    for r in records:
        parts.append(f"# Verifier record, {r['sha'][:7]}\n\n{r.get('text') or '(none)'}")
        parts.append(f"# Codex review, {r['sha'][:7]}\n\n{r.get('gpt_text') or '(none)'}")
    parts.append(f"# Diff\n\n```diff\n{diff}\n```")
    return "\n\n".join(parts)


def merge_check(text: str) -> dict:
    """{"merge", "reason", "session"} from a fresh headless Claude with no tools, in an empty folder with every
    customization off (--safe-mode): run inside the PR's worktree it also read the PR branch's own CLAUDE.md, so a PR
    could rewrite the rule it is judged by (verifier on c470756). One that cannot answer is a no: the PR goes to the
    user with what it said."""
    cmd = ["claude", "-p", "Decide whether this pull request merges without the user. The input is on stdin.",
           "--safe-mode", "--model", os.environ.get("MERGE_CHECK_MODEL", "claude-opus-5-5"),
           "--append-system-prompt-file", str(HERE / "skills" / "code-review" / "merge-check.md"),
           "--tools", "", "--output-format", "json", "--json-schema", json.dumps(CHECK_SCHEMA)]

    def no(why: str) -> dict:
        return {"merge": False, "reason": f"the merge check could not answer: {why.strip()[:300]}", "session": ""}
    try:
        run = subprocess.run(cmd, input=text, cwd=tempfile.mkdtemp(prefix="merge-check-"), capture_output=True,
                             text=True, timeout=900)
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


CI_WORDS = {"none": "none", "ok": "passing", "pending": "running", "failing": "failing"}
MERGEABLE_WORDS = {"MERGEABLE": "no conflicts", "CONFLICTING": "conflicts", "UNKNOWN": "still checking"}


def message(pr: dict, merge: bool, reasons: list[str], tiers: dict, status: dict, mode: str,
            merged_sha: str | None, error: str | None = None, check: dict | None = None,
            problems: list[str] | None = None) -> str:
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
    lines = [f"*[{repo} #{pr['number']}] {head}* — {pr['title']}",
             f"• Review {status['review']} · Tests {status['verify']} · CI {CI_WORDS.get(status['ci'], status['ci'])}"
             f" · {MERGEABLE_WORDS.get(status['mergeable'], status['mergeable'])}",
             "• Risk (any \"high\" needs you): " + " · ".join(f"{k} {v or 'none'}" for k, v in tiers.items())]
    if error:
        lines.append(f"• The merge command failed: {error}")
    elif merged_sha == UNKNOWN:
        lines.append("• Merged, but the merge commit could not be read back. To undo it, use Revert on the PR page")
    elif merged_sha:
        lines.append(f"• To undo: `git revert {merged_sha[:7]}` or Revert on the PR page")
    elif not merge:
        lines.append("• Why it was not merged: " + ", ".join(reasons))
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("pr", type=int)
    ap.add_argument("--repo", type=pathlib.Path, default=pathlib.Path.cwd())
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", action="store_true",
                    help="send to Slack even a reason the author could fix (/pr step 9, after three rounds)")
    a = ap.parse_args(argv)

    repo = a.repo.resolve()
    pr = json.loads(gh("pr", "view", str(a.pr), "--json",
                       "number,title,url,state,baseRefName,headRefOid,body,mergeable,statusCheckRollup", cwd=repo))
    common = subprocess.run(["git", "-C", str(repo), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            check=True, capture_output=True, text=True).stdout.strip()
    records = load_records(pathlib.Path(common) / "gate", pr["headRefOid"])
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
    merge = not reasons

    check = None
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
            check = merge_check(check_input(pr, issues, records, diff, rules))
            if not check["merge"]:
                merge, for_user = False, True
                reasons.append(f"Merge check (Claude): {check['reason']}")

    merged_sha = error = None
    problems: list[str] = []
    if merge and mode == "on" and not a.dry_run:
        # Branch protection, a draft, or a push after the review make the merge fail: report it, do not stop silently
        # (verifier note on 08df90d).
        try:
            gh("pr", "merge", str(a.pr), "--squash", "--match-head-commit", pr["headRefOid"], cwd=repo)
        except subprocess.CalledProcessError as e:
            error = ((e.stderr or "").strip().splitlines() or [str(e)])[-1][:300]
        if not error:
            # The merge happened; a failed lookup after it must not read as a failed merge (verifier note on f07e72f).
            try:
                merged_sha = json.loads(gh("pr", "view", str(a.pr), "--json", "mergeCommit",
                                           cwd=repo))["mergeCommit"]["oid"]
            except (subprocess.CalledProcessError, KeyError, TypeError, ValueError):
                merged_sha = UNKNOWN
            problems = close_issues(issues, pr, merged_sha, repo)
            try:
                gh("pr", "comment", str(a.pr), "--body",
                   f"Merge check (Claude, session {check['session'][:8]}): merged. {check['reason']}", cwd=repo)
            except subprocess.CalledProcessError as e:
                problems.append(f"could not comment the merge check on the PR: {(e.stderr or str(e)).strip()[:200]}")
    text = message(pr, merge, reasons, tiers, status, "dry-run" if a.dry_run else mode, merged_sha, error,
                   check, problems)
    print(text)
    if not a.dry_run and (for_user or a.report or error or problems or mode != "on"):
        try:
            print(f"[slack] {post_slack(text)}")
        except Exception as e:                          # after a merge, a Slack failure must not hide it
            print(f"[slack] not sent: {e}")
    shown = "dry-run" if a.dry_run else mode
    verdict = ("MERGE FAILED" if error else "MERGED" if merged_sha
               else f"WOULD MERGE ({shown}, not merged)" if merge else "TO USER")
    print(f"automerge: {verdict} · #{a.pr} · {pr['headRefOid'][:7]} · mode {mode}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
