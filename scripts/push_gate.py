#!/usr/bin/env python3
"""Push gate: a branch leaves this machine only when an independent verifier has recorded a verdict for its tip.

Git runs this as the pre-push hook (githooks/pre-push) and passes `<local ref> <local sha> <remote ref> <remote sha>`
lines on stdin. Each pushed branch tip needs `<git common dir>/gate/<sha>.review.md`, which only record_review.py
writes, from a verifier session that verify_fresh.sh started. Any review verdict passes, so /pr can still open a PR
with ISSUES and say why (commands/pr.md step 4); a verify FAIL does not. Branch deletes, tags, and tips already on
the remote's main pass, because nothing unreviewed leaves.

Turn it on in a repo: `git -C <repo> config core.hooksPath ~/projects/hhmode/githooks`. That replaces the repo's
.git/hooks, so a repo with hooks of its own (k-defense-kg: scripts/githooks, which has its own gate) keeps those.

Why (log.md 2026-10-30): hhmode #12 was opened and merged without a verifier run. Nothing stopped it, because the
gate that blocks such a push lived inside k-defense-kg (its scripts/gate.py, 2026-10-27) and not in the harness.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from automerge import HEAD_RE, record_fields  # noqa: E402  the record's reader, shared with the merge check

ZERO = "0" * 40
HOW = ("검증은 `/pr` 4단계: `bash ~/projects/hhmode/scripts/verify_fresh.sh <작업 폴더> standard` "
       "(위험도 높음이면 full). 기록은 커밋마다 따로라, 새 커밋을 만들면 다시 돌려야 한다.")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


def gate_dir() -> pathlib.Path:
    return pathlib.Path(git("rev-parse", "--path-format=absolute", "--git-common-dir")) / "gate"


def on_remote_main(sha: str, remote: str) -> bool:
    ref = f"refs/remotes/{remote}/main"
    if subprocess.run(["git", "rev-parse", "-q", "--verify", ref], capture_output=True).returncode:
        return False
    return subprocess.run(["git", "merge-base", "--is-ancestor", sha, ref], capture_output=True).returncode == 0


def problems(stdin_text: str, gdir: pathlib.Path, remote: str, on_main=on_remote_main) -> list[str]:
    out = []
    for line in stdin_text.splitlines():
        parts = line.split()
        if len(parts) != 4:
            continue
        sha, dest = parts[1], parts[2]
        # The destination decides: `git push origin refs/tags/x:refs/heads/task` pushes a branch (GPT lane on 8c86c3c).
        if sha == ZERO or dest.startswith("refs/tags/") or on_main(sha, remote):
            continue
        name = dest.removeprefix("refs/heads/")
        rec = gdir / f"{sha}.review.md"
        text = rec.read_text(encoding="utf-8") if rec.exists() else ""
        head = HEAD_RE.match(text)
        if not head or not sha.startswith(head.group(2)):
            out.append(f"  {name} ({sha[:7]}): 독립 검증 기록이 없다")
        elif record_fields(text)["verify"] == "FAIL":
            out.append(f"  {name} ({sha[:7]}): 테스트(verify)가 실패한 기록이다 — 고친 커밋을 다시 검증할 것")
    return out


def main(argv: list[str]) -> int:
    remote = argv[1] if len(argv) > 1 else "origin"
    bad = problems(sys.stdin.read(), gate_dir(), remote)
    if bad:
        print("push 막음 — 독립 검증을 거치지 않은 커밋이다 (hhmode scripts/push_gate.py):", file=sys.stderr)
        print("\n".join(bad), file=sys.stderr)
        print(HOW, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
