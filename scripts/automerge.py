#!/usr/bin/env python3
"""Merge a PR without the user only when every independent check says it is safe, and report to Slack either way.

Run by /pr after the verifier: `python3 ~/projects/hhmode/scripts/automerge.py <PR number>` from the task worktree.

A PR merges on its own only when all of these hold for its head commit:
  - the verifier's record says Review PASS and verify PASS (gate/<sha>.review.md, written by record_review.py);
  - the GPT lane's review exists (gate/<sha>.gpt.md, copied by verify_fresh.sh);
  - the highest of the author's tier (PR body), the verifier's and the GPT lane's is low (references/tiers.md);
    a re-review scoped `since` an earlier commit also counts the tiers recorded for that commit;
  - GitHub says the PR is open and mergeable, and no check is failing or still running.
Anything else goes to the user, with the reasons. The merge pins the reviewed commit (--match-head-commit), so a
push after the review cannot ride along (pstack: only a clean verdict on the patch that merges authorizes it).

Mode, from local/automerge (gitignored): `on` merges; anything else, or no file, only reports what it would have
done (the trial week). Slack: local/notify.json {"token_file": "...", "channel": "..."}; without it the message
is printed. --dry-run prints and does nothing else.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent.parent          # hhmode root
ORDER = {"low": 0, "medium": 1, "high": 2}
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
    m = re.search(r"^## Tier\s*\n+\s*`*(low|medium|high)\b", text or "", re.M | re.I)
    return m.group(1).lower() if m else None


def record_fields(text: str) -> dict:
    head = HEAD_RE.match(text or "")
    meta = re.search(r"<!-- verifier-session: [^;]+; verify: (\w+); (?:tier: (\w+); )?lanes:", text or "")
    return {"review": head.group(1) if head else None, "since": head.group(4) if head else None,
            "verify": meta.group(1) if meta else None, "tier": meta.group(2) if meta else None}


def checks_state(rollup: list) -> str:
    """`ok`, `pending` or `failing` for GitHub's statusCheckRollup. No checks at all (hhmode has no CI) is ok."""
    state = "ok"
    for c in rollup or []:
        status = (c.get("status") or "").upper()
        concl = (c.get("conclusion") or c.get("state") or "").upper()
        if concl in {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"}:
            return "failing"
        if status in {"QUEUED", "IN_PROGRESS", "PENDING", "WAITING"} or concl in {"PENDING", "EXPECTED", ""}:
            state = "pending"
    return state


def decide(pr: dict, records: list[dict]) -> tuple[bool, list[str], dict]:
    """Pure. `records`: the head commit's first, then each `since` ancestor's, each {review, verify, tier, gpt}.
    Returns (merge, reasons it may not, tiers seen)."""
    reasons, head = [], records[0]
    if pr.get("state") != "OPEN":
        reasons.append(f"PR이 열려 있지 않음({pr.get('state')})")
    if pr.get("baseRefName") != "main":
        # The verifier reviews `origin/main...HEAD`; into another base the merge would carry changes nobody reviewed
        # (GPT lane, 2026-10-29).
        reasons.append(f"병합 대상이 main 이 아님({pr.get('baseRefName')}) — 리뷰는 main 기준")
    if head["review"] != "PASS":
        reasons.append(f"리뷰 {head['review'] or '기록 없음'}")
    if head["verify"] != "PASS":
        reasons.append(f"검증 {head['verify'] or '기록 없음'}")
    tiers = {"작성자": author_tier(pr.get("body", ""))}
    for i, r in enumerate(records):
        tag = "" if i == 0 else f"({r.get('sha', '')[:7]})"
        tiers[f"검증기{tag}"] = r["tier"]
        tiers[f"GPT{tag}"] = r["gpt"]
    missing = [k for k, v in tiers.items() if v not in ORDER]
    if missing:
        reasons.append("등급 없음: " + ", ".join(missing))
    top = max((v for v in tiers.values() if v in ORDER), key=ORDER.get, default=None)
    if top and top != "low":
        reasons.append(f"등급 {top}")
    if pr.get("mergeable") != "MERGEABLE":
        reasons.append(f"병합 불가 상태({pr.get('mergeable')})")
    ci = checks_state(pr.get("statusCheckRollup"))
    if ci != "ok":
        reasons.append({"failing": "CI 실패", "pending": "CI 진행 중"}[ci])
    return (not reasons, reasons, tiers)


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
        f["gpt"] = gpt_tier(gpt.read_text(encoding="utf-8")) if gpt else None
        f["sha"] = rec.name.split(".")[0] if rec else sha
        out.append(f)
        sha = f["since"]
    return out


def message(pr: dict, merge: bool, reasons: list[str], tiers: dict, mode: str, merged_sha: str | None) -> str:
    tier_s = ", ".join(f"{k} {v or '없음'}" for k, v in tiers.items())
    title = f"#{pr['number']} {pr['title']}"
    if merge and merged_sha:
        return (f"*자동 병합* {title}\n• 근거: 리뷰·검증 PASS, 등급 {tier_s}, CI 통과\n"
                f"• 되돌리기: `git revert {(merged_sha or '?')[:7]}` 또는 PR 화면의 Revert\n{pr['url']}")
    if merge:
        why = "[dry-run]" if mode == "dry-run" else "[시험 운영]"
        return (f"*{why} 자동 병합 대상이었음* {title} — 실제 병합은 안 함\n"
                f"• 근거: 리뷰·검증 PASS, 등급 {tier_s}, CI 통과\n{pr['url']}")
    return f"*확인 필요* {title}\n• 이유: {'; '.join(reasons)}\n• 등급: {tier_s}\n{pr['url']}"


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
    a = ap.parse_args(argv)

    repo = a.repo.resolve()
    pr = json.loads(gh("pr", "view", str(a.pr), "--json",
                       "number,title,url,state,baseRefName,headRefOid,body,mergeable,statusCheckRollup", cwd=repo))
    common = subprocess.run(["git", "-C", str(repo), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            check=True, capture_output=True, text=True).stdout.strip()
    records = load_records(pathlib.Path(common) / "gate", pr["headRefOid"])
    merge, reasons, tiers = decide(pr, records)
    mode_file = HERE / "local" / "automerge"
    mode = mode_file.read_text().strip() if mode_file.exists() else "shadow"

    merged_sha = None
    if merge and mode == "on" and not a.dry_run:
        gh("pr", "merge", str(a.pr), "--squash", "--match-head-commit", pr["headRefOid"], cwd=repo)
        merged_sha = json.loads(gh("pr", "view", str(a.pr), "--json", "mergeCommit", cwd=repo))["mergeCommit"]["oid"]
    text = message(pr, merge, reasons, tiers, "dry-run" if a.dry_run else mode, merged_sha)
    print(text)
    if not a.dry_run:
        print(f"[slack] {post_slack(text)}")
    shown = "dry-run" if a.dry_run else mode
    verdict = "MERGED" if merged_sha else (f"WOULD MERGE ({shown}, not merged)" if merge else "TO USER")
    print(f"automerge: {verdict} · #{a.pr} · {pr['headRefOid'][:7]} · mode {mode}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
