# Failure log

One line per incident where the agent got something wrong or I repeated an instruction. When the same line appears twice, promote it to a skill, a principle, or a script (`principles/encode-lessons-in-structure.md`).

Format: `YYYY-MM-DD | repo | what happened | action taken`

2026-09-22 | autore | Re-ran an experiment that prior work had already answered | hillclimb step 1: prior-work check
2026-09-29 | autore | Same failure again | second occurrence, encoded as hillclimb step 1
2026-07-06 | code-review | Three identical reviewer runs produced near-identical Majors | replaced with three persona-diverse reviewers
2026-10-26 | k-defense-kg | /hillclimb started on a tree with 129 uncommitted changes; revert would have erased user work | hillclimb step 4: clean-tree check added (first occurrence, encoded immediately: scope was unambiguous)
2026-10-26 | k-defense-kg | engine_perf hillclimb: 6 kept, cumulative 29.9s→~8s reported as a product of per-step ratios, never re-measured | hillclimb step 8: cumulative re-measure before report
2026-10-26 | k-defense-kg | chat_gate hillclimb: 2,640 model calls per hypothesis, 5 measured / 1 kept (+1.3%), 2.5h+ | hillclimb step 3: two-stage screening + minimum effect for small-effect metrics
2026-10-26 | k-defense-kg | engine_perf session BLOCKED by safety classifier twice (topic: attack-path planner), not a technical failure | none yet; frame tasks in defensive terms, see BWF CLAUDE.md "외부 서술이 분류기에 걸리면"
