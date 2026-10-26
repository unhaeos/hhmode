---
name: hillclimb
description: Iterative improvement of ONE measurable metric toward a target, for ML experiments or performance work. Use when the user says "hillclimb", "이 지표 올려봐", "계속 돌려서 개선해", or asks for a loop of try/measure/keep-or-revert rather than a one-off fix. Not for single bug fixes or one-shot experiments.
---

# Hillclimb

You own the metric and the integrity of the experiment. One change, one measurement, keep or revert. Never stack untested changes. Never claim a win from reading code.

Copy these steps into your todo list verbatim. A skipped step must be marked `skip: <reason>`.

1. **Check prior work before anything else.** Grep the repo (results/, docs/, dead-ends.md, HANDOFF.md, CLAUDE.md) for the same hypothesis. If prior work already answers it, report that and stop. (Recorded failure: 2026-09-22 and 2026-09-29 in autore, experiments repeated that earlier runs had answered.)
2. **Fix the metric and the stop predicate.** One metric, the direction that counts as better, and a predicate that pairs a target with a floor on attempts ("≥ 10% over baseline AND ≥ 8 attempts"). Use the user's numbers if given. Do not relax the predicate later.
3. **Build the measurement harness, prove it is sensitive, then freeze it.** One repeatable command emits the metric. Run it on a case that should be worse and a case that should be better; if it cannot separate them, fix the harness, not the hypothesis. Sample enough to clear noise (median of N seeds, not one run). Print error count and work-done count alongside the metric. Apply `~/projects/harness/principles/explain-the-number.md` before freezing.
4. **Record the baseline** with the frozen harness, plus a green run of the regression gate (tests / sanity checks that must keep passing). No change before this row exists.
5. **Open `decision.tsv`** (gitignored, in the experiment dir). One row per attempt: `id  hypothesis  change  before  after  delta  gate  verdict(kept|reverted)  note`. Read it before every attempt.
6. **Loop, one hypothesis per iteration.** Each hypothesis names a mechanism ("X because Y"), not "try tweaking Z". Measure before/after with the frozen harness, run the gate. Keep only if the metric moves past noise and the gate is green; otherwise revert in full. A change that "might help" is not kept. One commit per accepted change, `git add <files>` never `-A`. Log the row either way.
7. **Push past the first plateau.** After several rejects in a row: pivot category, combine near-misses, re-read the source, apply `~/projects/harness/principles/attack-the-premise.md`. Correctness beats the number: revert a win that breaks behavior.
8. **Stop** when the predicate is met, or remaining ideas are marginal. Do not quit while cheap untried hypotheses remain. If stuck, say so instead of spinning.

**Reply:** metric and target; baseline → final with delta; attempts (kept / reverted); each accepted change on one line; `decision.tsv` path; the best next idea if pushed further. Verdict line: `PASS` (predicate met), `ISSUES` (improved, predicate not met), `BLOCKED` (harness or repro could not be established). Label each claim `measured` / `inferred` / `guess`.

Adapted from pstack playbook `hillclimb` (Lauren Tan, MIT). Removed: Cursor subagent/model routing, worktree fan-out, PR steps.
