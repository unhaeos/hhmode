#!/usr/bin/env python3
"""Build the GPT reviewer's input: the diff, then each changed file as it is after the change.

Codex cannot run commands on this machine (its bundled bubblewrap fails with "loopback: Failed RTM_NEWADDR:
Operation not permitted", with or without Claude Code's sandbox, measured 2026-10-29), so it cannot read the
repo itself. The full files give it the context a diff-only reviewer lacks: in k-defense-kg's review log the
diff-only lane raised no P0/P1 in 88 rows.

Usage: gpt_review_input.py <worktree> <base sha>   (prints markdown to stdout)
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

FILE_CAP = 60_000       # bytes per file; longer files are cut and say so
TOTAL_CAP = 400_000     # bytes of file text in all; files past it are listed by name only


def git(repo: pathlib.Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def build(repo: pathlib.Path, base: str) -> str:
    diff = git(repo, "diff", f"{base}..HEAD")
    names = [n for n in git(repo, "diff", "--name-only", "--diff-filter=d", f"{base}..HEAD").splitlines() if n]
    out = [f"## Diff ({base[:7]}..HEAD)\n\n```diff\n{diff}```\n", "## Changed files after the change\n"]
    used = 0
    for name in names:
        path = repo / name
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            out.append(f"### {name}\n\n(binary or unreadable, not included)\n")
            continue
        if used >= TOTAL_CAP:
            out.append(f"### {name}\n\n(not included: input size limit reached)\n")
            continue
        cut = text[:FILE_CAP]
        used += len(cut)
        note = f"\n(cut at {FILE_CAP} of {len(text)} characters)" if len(text) > FILE_CAP else ""
        out.append(f"### {name}\n\n```\n{cut}\n```{note}\n")
    return "\n".join(out)


if __name__ == "__main__":
    print(build(pathlib.Path(sys.argv[1]), sys.argv[2]))
