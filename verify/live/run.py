#!/usr/bin/env python3
"""Run the live checks in verify/live/: invariants that drive hhmode's scripts with many generated inputs.

A live check is a file `check_*.py` here that defines
  PATHS      the repo paths it guards (fnmatch patterns); the runner picks a check when a changed path matches
  INVARIANT  one sentence: what must always hold
  ORIGIN     where it came from (the review finding, PR or commit that found the bug class)
  check(rng) one random case; raise AssertionError with the counterexample when the invariant fails

Unlike `.verify/` scripts a verifier writes and throws away, these stay in the repo, so a bug class found once is
checked on every later change. They cost time, so the runner picks checks by changed path, keeps a time budget,
and logs each run to `<git common dir>/verify-live-history.tsv`; `--report` reads that log to find checks that are
slow and never fail (see README.md, "Keeping the set small").

Usage: run.py [--all | --since <ref>] [--cases N] [--budget SECONDS] [--seed N]
       run.py --report        per check: runs, failures, mean seconds, last failure
       run.py --map           print the path -> check map (MAP.md is this output)
Exit code: 0 when every check that ran held, 1 when one failed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import importlib.util
import pathlib
import random
import re
import subprocess
import sys
import time
import traceback

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True, capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stdout.strip()


def load_checks() -> list:
    sys.path.insert(0, str(ROOT / "scripts"))
    out = []
    for path in sorted(HERE.glob("check_*.py")):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for name in ("PATHS", "INVARIANT", "ORIGIN", "check"):
            if not hasattr(mod, name):
                sys.exit(f"{path.name}: missing {name}")
        out.append(mod)
    return out


def changed_paths(since: str) -> list[str]:
    return [p for p in git("diff", "--name-only", f"{since}...HEAD").splitlines() if p]


# A change to any of these can change what every script does, so every check runs.
RUN_ALL = ["pyproject.toml", "uv.lock", "requirements*.txt", ".python-version", "verify/live/*"]


def importers() -> dict[str, set[str]]:
    """scripts/<a>.py -> the scripts/<b>.py files that import it, directly or through others (imports inside
    functions count: record_review imports review_weight there)."""
    mods = {p.stem: p for p in (ROOT / "scripts").glob("*.py")}
    uses = {m: set(re.findall(r"^\s*(?:from|import)\s+(\w+)", p.read_text(encoding="utf-8"), re.M)) & set(mods)
            for m, p in mods.items()}
    out: dict[str, set[str]] = {}
    for m in mods:
        seen, todo = set(), [m]
        while todo:
            cur = todo.pop()
            for other, deps in uses.items():
                if cur in deps and other not in seen:
                    seen.add(other); todo.append(other)
        out[f"scripts/{m}.py"] = {f"scripts/{o}.py" for o in seen}
    return out


def expand(paths: list[str]) -> list[str] | None:
    """The changed paths plus every script that imports one of them; None when every check must run."""
    if any(fnmatch.fnmatch(p, pat) for p in paths for pat in RUN_ALL):
        return None
    # A deleted script is no longer in the import graph, so whoever used it cannot be found: run everything.
    if any(fnmatch.fnmatch(p, "scripts/*.py") and not (ROOT / p).exists() for p in paths):
        return None
    graph, out = importers(), set(paths)
    for p in paths:
        out |= graph.get(p, set())
    return sorted(out)


def picks(mod, paths: list[str]) -> bool:
    return any(fnmatch.fnmatch(p, pat) for p in paths for pat in mod.PATHS)


def history_file() -> pathlib.Path:
    return pathlib.Path(git("rev-parse", "--path-format=absolute", "--git-common-dir")) / "verify-live-history.tsv"


def run(mods: list, cases: int, budget: float, seed: int) -> int:
    log = history_file()
    sha = git("rev-parse", "--short", "HEAD")
    start, failed = time.monotonic(), 0
    for mod in mods:
        if time.monotonic() - start > budget:
            print(f"SKIP  {mod.__name__}: time budget of {budget:.0f}s used up")
            continue
        rng, t0, result, note = random.Random(seed), time.monotonic(), "PASS", ""
        try:
            for _ in range(cases):
                mod.check(rng)
        except AssertionError as e:
            result, note, failed = "FAIL", str(e).splitlines()[0][:300] if str(e) else "assertion failed", failed + 1
        except Exception as e:                      # a crash in the code under test is a failure too
            result, note, failed = "FAIL", f"{type(e).__name__}: {e}"[:300], failed + 1
            traceback.print_exc()
        secs = time.monotonic() - t0
        print(f"{result:5} {mod.__name__} ({secs:.1f}s){'  ' + note if note else ''}")
        with log.open("a", encoding="utf-8") as f:
            f.write("\t".join([dt.datetime.now().isoformat(timespec="seconds"), sha, mod.__name__, result,
                               f"{secs:.2f}", note.replace("\t", " ")]) + "\n")
    return 1 if failed else 0


def report() -> None:
    rows = [l.split("\t") for l in history_file().read_text(encoding="utf-8").splitlines()] if history_file().exists() else []
    stats: dict[str, list] = {}
    for when, sha, name, result, secs, *note in rows:
        s = stats.setdefault(name, [0, 0, 0.0, "-"])
        s[0] += 1; s[2] += float(secs)
        if result == "FAIL":
            s[1] += 1; s[3] = f"{when} {sha}"
    print(f"{'check':40} {'runs':>5} {'fails':>5} {'mean s':>7}  last failure")
    for name, (n, fails, total, last) in sorted(stats.items()):
        print(f"{name:40} {n:>5} {fails:>5} {total / n:>7.2f}  {last}")


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--all", action="store_true")
    g.add_argument("--since")
    g.add_argument("--report", action="store_true")
    g.add_argument("--map", action="store_true")
    ap.add_argument("--cases", type=int, default=200)
    ap.add_argument("--budget", type=float, default=120)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    if a.report:
        report(); return 0
    mods = load_checks()
    if a.map:
        for m in mods:
            print(f"- `{m.__name__}`: {m.INVARIANT}\n  - guards: {', '.join(m.PATHS)}\n  - origin: {m.ORIGIN}")
        return 0
    if not a.all:
        paths = expand(changed_paths(a.since or "origin/main"))
        if paths is not None:
            mods = [m for m in mods if picks(m, paths)]
        if not mods:
            print("no live check guards the changed paths"); return 0
    return run(mods, a.cases, a.budget, a.seed)


if __name__ == "__main__":
    sys.exit(main())
