# Prove It Works

Verify every output by checking the real thing directly. Not a proxy, not a self-report, not "it compiles", not "the script finished".

**Why:** Unverified work has unknown correctness. Indirect checks (file mtimes, a finished process, a cached result, an agent saying "done") feel cheaper than direct observation, but acting on a wrong inference costs more than the check.

- Read the actual value (the metric in the result file, the row count, the diff), not a derived view of it.
- When verification fails, suspect the observation method before the system.
- The strongest proof is a script that re-runs the same comparison. Keep its output as an artifact a reviewer can re-run.
- Report what you ran. If you could not run it, say so in the first line.

Adapted from pstack `principle-prove-it-works` (Lauren Tan, MIT).
