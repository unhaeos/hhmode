# Review lenses

Pass this to every bug reviewer. Use the lenses that apply; a one-line fix does not need an
architecture essay. Adapted from pstack `interrogate/references/rubric.md` (MIT) plus lessons
recorded in `log.md`.

## Correctness
- Edge cases: empty input, None/undefined, boundaries, very large input.
- Error paths: is a failure caught, propagated, or silently swallowed? Does a failure stop the
  dangerous next step, or does the code carry on?
- Idempotency: what if it runs twice, or a previous run died halfway? If the answer is "depends
  on what was left behind", a reconciliation step is missing.
- Concurrency: when several actors (sessions, cron, humans) touch the same files, branches, DB or
  ports, is access serialized by structure (locks, exclusive ownership, sequential phases) or by
  a convention that will not hold?
- Trace the path. Do not write "this could be None"; show the call chain that makes it None.

## Root cause vs symptom
- Does the change fix the real problem or paper over it (guard clause hiding a broken invariant,
  retry hiding a broken contract, cast silencing a modelling error)?
- A fix written as an instruction ("don't do X") where structure would hold: could it be a type,
  a lint rule, a hook, or a runtime check instead?

## Data safety (files, git, automation)
Lessons from 2026-10-27 reviews of agent tooling (log.md):
- Paths: non-ASCII (Korean) names, spaces, newlines, leading dashes, symlinks. Git quotes
  non-ASCII paths unless `-z` / `core.quotePath=false`.
- Git defaults that destroy local data: `merge` overwrites ignored files unless
  `--no-overwrite-ignore`; a commit that untracks a file deletes the working copy on update;
  renames hide the old path from `--diff-filter=D` unless `--no-renames`.
- Repeated runs (cron every N minutes): does each run redo work, re-log, or grow disk?
- Killed mid-run (reboot, SIGKILL): can a half-written artifact be mistaken for a finished one?
- A failed read treated as "empty" (e.g. `crontab -l || true`) followed by a write wipes data.
- Shell: `pipefail` with `grep -q` (SIGPIPE), `set -e` with `grep -v` on empty output, a
  backgrounded command losing stdin, `pkill -f` matching its own command line.

## Structure
- Validation at system boundaries, not scattered.
- Abstraction level, coupling, data model fit.
- Bolted-on vs integrated: if the requirement had been known from the start, would it look like
  this?

## Hooks and guards (Claude Code)
- A PreToolUse hook that exits 2 blocks the tool call. A missing script run as `python3 x.py`
  exits 2 too — wrap with `[ -f x ] || exit 0`.
- Parse commands as a whole (heredocs, line continuations, `cd X &&`, `git -C X`), not line by
  line or by word search.
