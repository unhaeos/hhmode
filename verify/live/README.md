# Live checks

Checks that drive hhmode's scripts with many generated inputs and assert one invariant each. They stay in the repo,
so a bug class found once (by review, a property test or a user) is checked on every later change. A verifier's
`.verify/` scripts are written in a throwaway worktree and deleted when the run ends; these are not.

Run: `python3 verify/live/run.py` (checks that guard what this branch changed, from `origin/main`),
`--all` (every check), `--report` (history per check), `--map` (writes the list below; `MAP.md` is its output).

## Adding a check

One file `check_<name>.py` with `PATHS`, `INVARIANT`, `ORIGIN` and `check(rng)` (see `run.py`). Write the invariant,
not the one input that broke: "the record reads back with the values it was written with, whatever the report
contains", not "a report quoting `tier: low`". Use only the standard library. A check runs `--cases` random cases
(200 by default) and must stay fast: a few seconds at most.

Add one when review, a property test or a user finds a bug whose class can come back. Before adding, look in
`MAP.md` for a check that already guards the same property, and widen it instead.

## What triggers a check

- A changed path that matches the check's `PATHS`.
- A changed script that a guarded script imports, directly or through others (`run.py` reads the imports).
- A deleted script: the import graph no longer has it, so every check runs.
- Any change to a dependency or runtime file (`pyproject.toml`, `uv.lock`, `requirements*.txt`, `.python-version`)
  or to `verify/live/` itself: every check runs.

What path selection cannot see (a new git or Python on the machine, an external service) needs the full set now and
then: run `--all` at least once a day and before a release.

## Keeping the set small

Checks cost time on every change, and a set that only grows becomes the next bottleneck. Every run is logged to
`<git common dir>/verify-live-history.tsv`, and `--report` shows runs, failures and mean seconds per check.

- **Merge** checks that guard the same property. Three egress checks become one "nothing outside the allow-list
  leaves the machine" check with the three cases as inputs.
- **Demote** a check that is slow (over 5 s) and has not failed in 50 runs: move it to the daily `--all` run by
  narrowing its `PATHS`, instead of every change.
- **Delete** a check whose feature is gone. Keep the `ORIGIN` line in the commit message.
- **Drift or bug**: when a check fails after a deliberate behaviour change, update the invariant in the same
  change and say so in the PR; when the behaviour change was not deliberate, it is a bug.

The time budget (`--budget`, 120 s) stops a run that grows past it and says which checks it skipped.
