#!/usr/bin/env python3
"""A per-repo ledger of what must survive compaction, printed back by a SessionStart hook.

Auto-compaction replaces the conversation with an LLM summary, so anything that lived only in the conversation can
drop out of it: a pending user decision, an instruction relayed from another session, a "do not touch". Write those
here the moment they appear; the hook prints them back after every compaction (and at session start), so the
summary does not have to carry them (hhmode #31, 2026-11-06).

  python3 scripts/ledger.py add "<text>"   append an item (run inside the repo it is about)
  python3 scripts/ledger.py show           print the open items
  python3 scripts/ledger.py done <n>       mark item n closed once it is resolved
  python3 scripts/ledger.py --hook         SessionStart hook: reads the hook input on stdin

The file is `<git common dir>/gate/ledger.md`: one per repo, shared by its worktrees and by every session working in
it, never committed. The hook always exits 0, so a session always starts.
"""
from __future__ import annotations

import contextlib
import datetime
import fcntl
import json
import pathlib
import re
import subprocess
import sys

ITEM = re.compile(r"^- \[(\d+)\] (.*)$")
CLOSED = "- closed "        # a resolved item stays in the file, marked, so a silent removal shows in a diff
HOW = ('ledger: record a pending decision, a relayed instruction or a "do not touch" the turn it appears, '
       'quoted verbatim with where it came from: `python3 ~/projects/hhmode/scripts/ledger.py add "<text>"`; '
       '`done <n>` once resolved.')


def git(cwd: pathlib.Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True,
                          timeout=5).stdout.strip()


def ledger_file(cwd: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")) / "gate" / "ledger.md"


def items(path: pathlib.Path) -> list[tuple[int, str]]:
    if not path.exists():
        return []
    return [(int(m[1]), m[2]) for m in map(ITEM.match, path.read_text(encoding="utf-8").splitlines()) if m]


def stamp() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


@contextlib.contextmanager
def locked(path: pathlib.Path):
    """One writer at a time: two sessions in one repo may add or close at once."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_suffix(".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def add(path: pathlib.Path, text: str) -> int:
    with locked(path):
        return _add(path, text)


def _add(path: pathlib.Path, text: str) -> int:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    # Numbers are never reused: a closed item keeps its number in its "closed" line.
    used = [int(m[1]) for m in (re.search(r"\[(\d+)\]", line) for line in lines) if m]
    n = max(used, default=0) + 1
    with path.open("a", encoding="utf-8") as f:            # append only: the other lines are never rewritten
        f.write(f"- [{n}] {stamp()} {' '.join(text.splitlines())}\n")   # one line per item; spaces kept
    return n


def done(path: pathlib.Path, n: int) -> bool:
    with locked(path):
        return _done(path, n)


def _done(path: pathlib.Path, n: int) -> bool:
    if n not in {r[0] for r in items(path)}:
        return False
    lines = path.read_text(encoding="utf-8").splitlines()
    out = [f"{CLOSED}{stamp()} {line[2:]}" if (m := ITEM.match(line)) and int(m[1]) == n else line for line in lines]
    path.write_text("".join(f"{line}\n" for line in out), encoding="utf-8")
    return True


def hook_text(event: dict) -> str:
    """What the SessionStart hook prints for this input; empty when there is nothing to say."""
    cwd = pathlib.Path(event.get("cwd") or ".")
    path = ledger_file(cwd)
    rows = items(path)
    lines = []
    if rows:
        lines.append(f"Ledger ({path}), open items:")
        lines += [f"- [{n}] {text}" for n, text in rows]
    if event.get("source") == "compact":
        # After a compaction the git state comes from git, not from the summary. A git failure here (no commit yet,
        # a timeout) drops only the git lines, never the items above (verifier on d22e8f9, P2).
        with contextlib.suppress(subprocess.SubprocessError, OSError):
            lines += git_state(cwd)
    else:
        lines.append(HOW)
    return "\n".join(lines)


def shown(rows: list[str], cap: int) -> list[str]:
    return [f"  {r}" for r in rows[:cap]] + ([f"  ... and {len(rows) - cap} more"] if len(rows) > cap else [])


def git_state(cwd: pathlib.Path) -> list[str]:
    lines = []
    lines.append(f"Branch: {git(cwd, 'rev-parse', '--abbrev-ref', 'HEAD')} at {git(cwd, 'rev-parse', '--short', 'HEAD')}")
    status = git(cwd, "status", "--short").splitlines()
    lines.append("Working tree: " + ("clean" if not status else f"{len(status)} changed"))
    lines += shown(status, 20)
    # Which files the branch changed, from git: summaries track file changes worst (Factory's compaction
    # evaluation, 2025: every method scored lowest on it).
    try:
        base = git(cwd, "merge-base", "HEAD", "origin/main")
        changed = git(cwd, "diff", "--name-only", base, "HEAD").splitlines()
    except subprocess.CalledProcessError:
        changed = []
    if changed:
        lines.append(f"Committed on this branch since origin/main: {len(changed)} files")
        lines += shown(changed, 30)
    return lines


def hook(stdin: str) -> str:
    try:
        return hook_text(json.loads(stdin or "{}"))
    except (ValueError, TypeError, OSError, subprocess.SubprocessError, AttributeError):
        return ""                      # not a repo, unreadable ledger, bad input: say nothing, start the session


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--hook"]:
        out = hook(sys.stdin.read())
        if out:
            print(out)
        return 0
    if not argv or argv[0] not in ("add", "show", "done"):
        print(__doc__.split("\n\n")[2])
        return 2
    try:
        path = ledger_file(pathlib.Path.cwd())
    except subprocess.CalledProcessError:
        print("ledger: not inside a git repo; run it in the repo the item is about")
        return 1
    if argv[0] == "add":
        if len(argv) < 2 or not " ".join(argv[1:]).strip():
            print('ledger: add needs the text, e.g. ledger.py add "PR #27 waits on the user\'s AC1 decision"')
            return 2
        print(f"ledger: added [{add(path, ' '.join(argv[1:]))}]")
    elif argv[0] == "show":
        rows = items(path)
        print("\n".join(f"- [{n}] {t}" for n, t in rows) if rows else "ledger: no open items")
    else:
        if len(argv) != 2 or not argv[1].isdigit():
            print("ledger: done needs the item number")
            return 2
        if not done(path, int(argv[1])):
            print(f"ledger: no item [{argv[1]}]")
            return 1
        print(f"ledger: closed [{argv[1]}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
