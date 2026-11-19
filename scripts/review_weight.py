#!/usr/bin/env python3
"""How much review a commit needs, in proportion to what changed since the last reviewed commit on its branch.

pstack autopilot-full: "a rebase, a merge-conflict resolution, or a minor fix gets a single verifier at the new head,
and a wording-only change gets none." verify_fresh.sh asks this before it starts anything:

  carry     only wording nobody executes changed since a review that passed: no verifier runs, the earlier record is
            carried over (record_review.py --carry)
  fix       a small change that adds no file: one verifier, lanes bug, verify and live, on the diff since
  standard  the first review on a branch, a large change, or a new file: every lane

The diff weighed is the scope, not plain since..head: when the branch merged origin/main after `since`, since..head
also carries main's changes, which the branch never made (k-defense-kg PR #302: main's re-recorded golden.json made
Codex rate a 3-file api change high). scope_base() gives the base the review lanes and Codex diff against too.

Usage: review_weight.py <repo> <since> <head>     prints `<kind><TAB><reason>`; <since> may be empty (no earlier review)
       review_weight.py --scope <repo> <since> <head>   prints the scope base (empty when <since> is)
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import forms  # noqa: E402
import record_review as rr

# Wording nobody executes: README.md, log.md and anything under docs/. A change that touches only these has nothing for
# a verifier to run or read as code. Paths are as `git diff --name-only` prints them, from the repo root.
WORDING_FILES = {"README.md", "log.md"}
WORDING_DIRS = ("docs/",)
# The most lines (added + deleted) a fix round may change. A first guess, to tune from the review log
# (~/.claude/review-log/*.tsv) (user, 2026-10-30).
FIX_LINES = 150


def changed_paths(repo: pathlib.Path, since: str, head: str) -> list[str]:
    # -z: names as they are, not quoted when they are not ASCII. --no-renames: a moved file counts at both paths, so
    # `git mv app.py docs/app.py` is not wording only (verifier and Codex on 9aadb3c).
    return [n for n in rr.git(repo, "diff", "-z", "--name-only", "--no-renames", f"{since}..{head}").split("\0") if n]


def new_closes(repo: pathlib.Path, since: str, head: str) -> list[int]:
    """Issues a commit after `since` says it closes: their criteria were never judged, so they need a verifier
    (verifier on 9aadb3c: a README-only commit that added `Closes #7` was carried with no criteria table)."""
    return forms.closes(rr.git(repo, "log", "--format=%B", f"{since}..{head}"))


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


def scope_base(repo: pathlib.Path | str, since: str | None, head: str, main: str = "origin/main") -> str:
    """The commit to diff against so the diff is only what the branch changed since `since`.

    If the branch merged `main` after `since`, the base is `since` with merge-base(main, head) merged in: a commit made
    here, not on any branch, so `base..head` leaves out what came from main. If that merge conflicts, the branch's own
    change cannot be told apart from main's, so the base is merge-base(main, head) and the whole branch is the scope.
    Otherwise (no merge of main since, or no `main` to ask) it is `since`. Empty when `since` is."""
    repo = pathlib.Path(repo)
    if not since:
        return ""
    since = rr.git(repo, "rev-parse", since)
    try:
        mb = rr.git(repo, "merge-base", main, head)
    except subprocess.CalledProcessError:
        return since
    if subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", mb, since]).returncode == 0:
        return since
    merged = subprocess.run(["git", "-C", str(repo), "merge-tree", "--write-tree", "--no-messages", since, mb],
                            capture_output=True, text=True)
    if merged.returncode != 0:                            # 1: conflicts; anything else: git could not merge
        return mb
    # Fixed author and dates, so the same inputs give the same commit id on every run.
    env = {**os.environ, "GIT_AUTHOR_NAME": "review scope", "GIT_AUTHOR_EMAIL": "scope@review",
           "GIT_COMMITTER_NAME": "review scope", "GIT_COMMITTER_EMAIL": "scope@review",
           "GIT_AUTHOR_DATE": "1970-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "1970-01-01T00:00:00Z"}
    return subprocess.run(["git", "-C", str(repo), "commit-tree", merged.stdout.split()[0], "-p", since, "-p", mb,
                           "-m", f"review scope: {since[:7]} with {main} merged"],
                          check=True, capture_output=True, text=True, env=env).stdout.strip()


def weight(repo: pathlib.Path | str, since: str | None, head: str) -> tuple[str, str]:
    """(kind, reason): kind is carry, fix or standard; reason is one plain sentence for the person running the gate."""
    repo = pathlib.Path(repo)
    if not since:
        return "standard", "There is no earlier review on this branch, so the whole change gets a full review."
    since, head = rr.git(repo, "rev-parse", since), rr.git(repo, "rev-parse", head)
    s7 = since[:7]
    rec = rr.gate_dir(repo) / f"{since}.review.md"      # the record is since's; the diff is the scope's
    base = scope_base(repo, since, head)
    paths = changed_paths(repo, base, head)
    # A commit since then that closes an issue rules out a carry only; the size checks below still decide between
    # fix and standard (verifier on 79691db: returning fix here skipped them).
    closes = new_closes(repo, base, head)
    if not closes and all(is_wording(p) for p in paths) and rec.exists() and \
            rr.carryable(rec.read_text(encoding="utf-8")):
        what = f"Only wording changed since {s7} ({', '.join(paths)})" if paths else f"Nothing changed since {s7}"
        return "carry", f"{what} and that review passed, so its result carries over without a new review."
    lines, binary = size(repo, base, head)
    new = added_files(repo, base, head)
    if binary:
        return "standard", f"A binary file changed since {s7}, so the change gets a full review."
    if lines > FIX_LINES:
        return "standard", f"{lines} lines changed since {s7}, more than {FIX_LINES}, so the change gets a full review."
    if new:
        return "standard", f"The change since {s7} adds a new file ({new[0]}), so it gets a full review."
    why = f"{lines} lines changed since {s7} and no file was added, so one verifier checks the fix."
    if closes:
        why += f" A commit since then closes #{closes[0]}, so the verifier judges its acceptance criteria."
    return "fix", why


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--scope":
        print(scope_base(pathlib.Path(sys.argv[2]), sys.argv[3], sys.argv[4]))
        sys.exit(0)
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    print("\t".join(weight(pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3])))
