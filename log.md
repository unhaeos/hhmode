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
2026-10-27 | k-defense-kg | 6 sessions shared one working tree; a bulk commit (4483984, 234 files) swallowed another session's in-flight experiment | repo CLAUDE.md: one task = one worktree = one PR, PreToolUse guard on the main checkout, flock for DB/GPU; /pr verifies in a worktree with an independent reviewer and risk tier; /land merges one PR at a time
2026-10-27 | hhmode | pr.md said 'Testing / Risk / How to revert are the three the Claude Code team requires' — not in the 2026-10-15 Claude Code review post (it describes risk tiers, review before the PR, merge queue); no other source checked | attribution removed, sections kept
2026-10-27 | hhmode | code-review told reviewers "there is always room to improve" (noise) and used three same-model personas with no per-finding reproduction, and ran only when someone remembered | redesigned after pstack/Anthropic/OpenAI/Google/Meta: precision-first agents (agents/), validator per P0/P1, automatic from /pr, PR comment, review-log for fix rate
