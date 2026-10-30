#!/usr/bin/env python3
"""How much review a commit needs, in proportion to what changed since the last reviewed commit on its branch.

pstack autopilot-full: "a rebase, a merge-conflict resolution, or a minor fix gets a single verifier at the new head,
and a wording-only change gets none." verify_fresh.sh asks this before it starts anything:

  carry     only wording nobody executes changed since a review that passed: no verifier runs, the earlier record is
            carried over (record_review.py --carry)
  fix       a small change that adds no file: one verifier, lanes bug, verify and live, on the diff since
  standard  the first review on a branch, a large change, or a new file: every lane

Usage: review_weight.py <repo> <since> <head>     prints `<kind><TAB><reason>`; <since> may be empty (no earlier review)
"""
from __future__ import annotations

import pathlib
import sys

import record_review as rr

# Wording nobody executes: README.md, log.md and anything under docs/. A change that touches only these has nothing for
# a verifier to run or read as code. Paths are as `git diff --name-only` prints them, from the repo root.
WORDING_FILES = {"README.md", "log.md"}
WORDING_DIRS = ("docs/",)
# The most lines (added + deleted) a fix round may change. A first guess, to tune from the review log
# (~/.claude/review-log/*.tsv) (user, 2026-10-30).
FIX_LINES = 150


def changed_paths(repo: pathlib.Path, since: str, head: str) -> list[str]:
    # -z: names as they are, not quoted when they are not ASCII
    return [n for n in rr.git(repo, "diff", "-z", "--name-only", f"{since}..{head}").split("\0") if n]


def is_wording(path: str) -> bool:
    return path in WORDING_FILES or path.startswith(WORDING_DIRS)


def size(repo: pathlib.Path, since: str, head: str) -> tuple[int, bool]:
    """(lines added + deleted, whether a binary file changed). --no-renames: a moved file counts as deleted and added,
    so a move is judged by what it carries, not trusted as a no-op."""
    lines, binary = 0, False
    for row in rr.git(repo, "diff", "--no-renames", "--numstat", f"{since}..{head}").splitlines():
        added, deleted, _ = row.split("\t", 2)
        if added == "-":                                  # git prints "-" for a binary file
            binary = True
        else:
            lines += int(added) + int(deleted)
    return lines, binary


def added_files(repo: pathlib.Path, since: str, head: str) -> list[str]:
    out = rr.git(repo, "diff", "-z", "--no-renames", "--name-only", "--diff-filter=A", f"{since}..{head}")
    return [n for n in out.split("\0") if n]


def weight(repo: pathlib.Path | str, since: str | None, head: str) -> tuple[str, str]:
    """(kind, reason): kind is carry, fix or standard; reason is one plain sentence for the person running the gate."""
    repo = pathlib.Path(repo)
    if not since:
        return "standard", "There is no earlier review on this branch, so the whole change gets a full review."
    since, head = rr.git(repo, "rev-parse", since), rr.git(repo, "rev-parse", head)
    s7 = since[:7]
    paths = changed_paths(repo, since, head)
    rec = rr.gate_dir(repo) / f"{since}.review.md"
    if all(is_wording(p) for p in paths) and rec.exists() and rr.carryable(rec.read_text(encoding="utf-8")):
        what = f"Only wording changed since {s7} ({', '.join(paths)})" if paths else f"Nothing changed since {s7}"
        return "carry", f"{what} and that review passed, so its result carries over without a new review."
    lines, binary = size(repo, since, head)
    new = added_files(repo, since, head)
    if binary:
        return "standard", f"A binary file changed since {s7}, so the change gets a full review."
    if lines > FIX_LINES:
        return "standard", f"{lines} lines changed since {s7}, more than {FIX_LINES}, so the change gets a full review."
    if new:
        return "standard", f"The change since {s7} adds a new file ({new[0]}), so it gets a full review."
    return "fix", f"{lines} lines changed since {s7} and no file was added, so one verifier checks the fix."


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    print("\t".join(weight(pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3])))
