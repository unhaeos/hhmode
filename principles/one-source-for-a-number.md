# One Source for a Number

A number you report (metric, AUROC, success rate, count) comes from one generated source that cites its inputs — never hand-typed from whichever result file happened to be open.

- **Open the authority before you quote.** A repo that produces numbers should have one map (an INDEX) naming, per question, the authoritative file or doc. Read it first. If two files hold the "same" number, only the one the map names counts; the rest are stale until proven otherwise.
- **Generate, don't transcribe.** Headline numbers (papers, dashboards, status docs) are generated from the authoritative store, not copied by hand into prose. A hand-copied number drifts the moment the run is rerun.
- **Version lives in git and a log, not in filenames.** Re-running overwrites one canonical path; history is a commit plus an append-only ledger line. `_v2` / `_fix` / `_final` / dated output names are the smell that builds the stale pile.
- **Quarantine, don't delete, what the map doesn't name.** Move unreferenced outputs out of the working directory so they cannot be grabbed again.

You skipped this when a number in a doc has no cited source, when the same metric sits in several result files with none marked authoritative, or when output filenames carry versions.

First failures: `log.md` 2026-10-28 (bwf).

Related: `explain-the-number` (what bounds the number) and `encode-lessons-in-structure` (make the single source a script, not a rule).
