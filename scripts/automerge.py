#!/usr/bin/env python3
"""Merge a PR without the user when the facts hold and a fresh Claude, the merge check, finds nothing for the user
to look at. Report to Slack only the PRs that need the user.

Run by /pr after CI: `python3 ~/projects/hhmode/scripts/automerge.py <PR number>` from the task worktree.

1. Facts, checked here for the PR's head commit. Any that fails stops the merge, and the merge check never starts:
  - the verifier's record says Review PASS and verify PASS (gate/<sha>.review.md, written by record_review.py);
  - the Codex review exists (gate/<sha>.gpt.md, copied by verify_fresh.sh);
  - nobody rated the risk high: not the author (PR body), the verifier, nor Codex (references/tiers.md); a
    re-review scoped `since` an earlier commit also counts that commit's tiers;
  - GitHub says the PR is open into main and mergeable, and no check is failing or still running.
2. The merge check: a fresh headless Claude that wrote and verified nothing reads the PR, the issues it closes, the
   repo's CLAUDE.md, the records and the diff (skills/code-review/merge-check.md) and answers merge or not, with a
   reason. A repo rule that sends this kind of change to the user wins over the tiers above.
3. The merge pins the reviewed commit (--match-head-commit), so a push after the review cannot ride along (pstack:
   only a clean verdict on the patch that merges authorizes it). Then each issue the PR closes is closed if GitHub
   left it open, and the merge check's reason goes on the PR as a comment.

Slack, only for what needs the user (user decision 2026-10-30): a high tier, a merge check that says no, a failed
merge or issue close, or --report (the author gives up after three rounds). A reason the author fixes (CI, review,
a conflict) is printed, not sent. Mode, from local/automerge (gitignored): `on` merges; anything else reports what
it would have done, to Slack. Slack target: local/notify.json {"token_file": "...", "channel": "..."}; without it
the message is printed. --dry-run prints the facts and does nothing else (no merge check).
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

HERE = pathlib.Path(__file__).resolve().parent.parent          # hhmode root
ORDER = {"low": 0, "medium": 1, "high": 2}
UNKNOWN = "unknown"                 # merged, but the merge commit could not be read back
MAX_AUTO = "medium"                 # the highest tier that merges without the user (user decision 2026-10-30)
TIER_KO = {"low": "낮음", "medium": "중간", "high": "높음"}
VERDICT_KO = {"PASS": "통과", "ISSUES": "지적 있음", "BLOCKED": "못 돌림", "FAIL": "실패"}
HEAD_RE = re.compile(r"^\*\*Review: (\w+)\*\* · ([0-9a-f]{7,40}) · (\w+)(?: · since ([0-9a-f]{7,40}))?")


def author_tier(body: str) -> str | None:
    """The tier in the PR body's "Risk tier:" field (a line that starts with it, bold allowed), or None when there is
    no such field, when it holds more than one tier word (the template's `low | medium | high` placeholder), or when
    two fields disagree. Prose that merely mentions a risk tier does not count (GPT lane on 08df90d)."""
    found = set()
    for line in (body or "").splitlines():
        m = re.match(r"^\s*\**\s*risk tier\s*:(.*)$", line, re.I)
        if m:
            words = set(re.findall(r"\b(low|medium|high)\b", m.group(1).lower()))
            if len(words) != 1:
                return None
            found |= words
    return found.pop() if len(found) == 1 else None


def gpt_tier(text: str) -> str | None:
    """The tier on the line after `## Tier`, or None unless that line holds exactly one tier word (an unfilled
    `low | medium | high` or `low-to-medium` must not read as low; verifier note on 08df90d)."""
    m = re.search(r"^## Tier\s*\n+(.*)$", text or "", re.M | re.I)
    words = set(re.findall(r"\b(low|medium|high)\b", m.group(1).lower())) if m else set()
    return words.pop() if len(words) == 1 else None


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
    status = {"review": VERDICT_KO.get(head["review"], head["review"] or "기록 없음"),
              "verify": VERDICT_KO.get(head["verify"], head["verify"] or "기록 없음"),
              "ci": checks_state(pr.get("statusCheckRollup")), "mergeable": pr.get("mergeable")}
    if pr.get("state") != "OPEN":
        reasons.append(f"PR이 열려 있지 않음({pr.get('state')})")
    if pr.get("baseRefName") != "main":
        # The verifier reviews `origin/main...HEAD`; into another base the merge would carry changes nobody reviewed
        # (GPT lane, 2026-10-29).
        reasons.append(f"병합 대상이 main 이 아님({pr.get('baseRefName')}) — 리뷰는 main 기준")
    if head["review"] != "PASS":
        reasons.append(f"리뷰 {status['review']}")
    if head["verify"] != "PASS":
        reasons.append(f"검증 {status['verify']}")
    tiers = {"PR 쓴 에이전트": author_tier(pr.get("body", ""))}
    if tiers["PR 쓴 에이전트"] is None:
        reasons.append("PR 본문의 위험도 칸이 없거나 비어 있음")
    for i, r in enumerate(records):
        tag = "" if i == 0 else f"({r.get('sha', '')[:7]})"
        tiers[f"Claude 검증{tag}"] = r["tier"]
        tiers[f"Codex 리뷰{tag}"] = r["gpt"]
        if r["tier"] is None:
            reasons.append(f"Claude 검증{tag} 기록 없음" if r["review"] is None
                           else f"Claude 검증{tag} 기록에 위험도가 없음(위험도 칸이 생기기 전 기록)")
        if r["gpt"] is None:
            reasons.append(f"이 검증{tag}에서 Codex 리뷰가 돌지 않았거나 위험도를 못 읽음")
    top = max((v for v in tiers.values() if v in ORDER), key=ORDER.get, default=None)
    if top and ORDER[top] > ORDER[MAX_AUTO]:
        reasons.append(f"위험도 {TIER_KO[top]}")
    if pr.get("mergeable") != "MERGEABLE":
        reasons.append(f"병합 불가 상태({pr.get('mergeable')})")
    if status["ci"] in {"pending", "failing"}:
        reasons.append({"failing": "CI 실패", "pending": "CI 진행 중"}[status["ci"]])
    return (not reasons, reasons, tiers, status)


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
        return {"merge": False, "reason": f"머지 확인 에이전트가 답하지 못함: {why.strip()[:300]}", "session": ""}
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
    return no(str(d.get("result") or run.stderr or "답이 비어 있음"))


def close_issues(issues: list[dict], pr: dict, merged: str, cwd) -> list[str]:
    """Close each issue the PR closes that GitHub left open. GitHub closes them itself a moment after the merge, so
    wait once before looking. Returns the ones that failed, for the user."""
    if issues:
        time.sleep(CLOSE_WAIT)
    by = f"#{pr['number']} 머지" + (f"({merged[:7]})" if merged and merged != UNKNOWN else "")
    failed = []
    for i in issues:
        try:
            if json.loads(gh("issue", "view", i["url"], "--json", "state", cwd=cwd))["state"] != "CLOSED":
                gh("issue", "close", i["url"], "--reason", "completed", "--comment", f"{by}로 완료", cwd=cwd)
        except subprocess.CalledProcessError as e:
            failed.append(f"이슈 #{i['number']} 닫기 실패: {(e.stderr or str(e)).strip()[:200]}")
    return failed


CI_KO = {"none": "없음", "ok": "통과", "pending": "진행 중", "failing": "실패"}
MERGEABLE_KO = {"MERGEABLE": "충돌 없음", "CONFLICTING": "충돌 있음", "UNKNOWN": "충돌 여부 확인 중"}


def message(pr: dict, merge: bool, reasons: list[str], tiers: dict, status: dict, mode: str,
            merged_sha: str | None, error: str | None = None, check: dict | None = None,
            problems: list[str] | None = None) -> str:
    m = re.search(r"github\.com/[^/]+/([^/]+)/pull/", pr.get("url", ""))
    repo = m.group(1) if m else "?"
    if error:
        head = "자동 병합 실패"
    elif merge and merged_sha:
        head = "자동 병합"
    elif merge:
        head = ("[dry-run]" if mode == "dry-run" else "[시험 운영]") + " 자동 병합 대상(실제 병합은 안 함)"
    else:
        head = "확인 필요"
    lines = [f"*[{repo} #{pr['number']}] {head}* — {pr['title']}",
             f"• 리뷰 {status['review']} · 테스트 {status['verify']} · CI {CI_KO.get(status['ci'], status['ci'])}"
             f" · {MERGEABLE_KO.get(status['mergeable'], status['mergeable'])}",
             "• 위험도(하나라도 '높음'이면 사용자 확인): "
             + " · ".join(f"{k} {TIER_KO.get(v, '없음')}" for k, v in tiers.items())]
    if error:
        lines.append(f"• 병합 명령이 실패함: {error}")
    elif merged_sha == UNKNOWN:
        lines.append("• 병합은 됐지만 병합 커밋 번호를 못 읽음. 되돌리기는 PR 화면의 Revert")
    elif merged_sha:
        lines.append(f"• 되돌리기: `git revert {merged_sha[:7]}` 또는 PR 화면의 Revert")
    elif not merge:
        lines.append("• 자동 병합 안 한 이유: " + ", ".join(reasons))
    if check and check["merge"]:
        lines.append(f"• 머지 확인(Claude): {check['reason']}")
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

    check, issues = None, []
    if merge and not a.dry_run:
        # Anything the check cannot read sends the PR to the user, with the reason, instead of crashing silently
        # after the facts passed (verifier on c470756).
        try:
            issues = closing_issues(pr, repo)
            diff = gh("pr", "diff", str(a.pr), cwd=repo)
            rules = repo_rules(pr, repo)
            unread = ("저장소 규칙(CLAUDE.md)을 못 읽음" if rules is None
                      else f"변경이 커서({len(diff)}자) 머지 확인이 다 읽을 수 없음" if len(diff) > DIFF_CAP else None)
        except subprocess.CalledProcessError as e:
            unread = f"머지 확인에 쓸 PR 정보를 못 읽음: {(e.stderr or str(e)).strip()[:200]}"
        if unread:
            merge, for_user = False, True
            reasons.append(unread)
        else:
            check = merge_check(check_input(pr, issues, records, diff, rules))
            if not check["merge"]:
                merge, for_user = False, True
                reasons.append(f"머지 확인(Claude): {check['reason']}")

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
                   f"머지 확인(Claude, 세션 {check['session'][:8]}): 머지함. {check['reason']}", cwd=repo)
            except subprocess.CalledProcessError as e:
                problems.append(f"PR에 머지 확인 댓글을 못 남김: {(e.stderr or str(e)).strip()[:200]}")
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
