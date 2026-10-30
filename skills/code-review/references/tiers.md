Risk tier. The change sets it, not the author. When unsure, take the higher one.

- **low**: only docs, comments, tests, or scripts nothing else imports (an experiment script, a test fixture).
  Nothing a user, another program or an agent sees behaves differently.
- **medium**: any behaviour change in code, prompts, skills, commands, agents, UI or tooling; any added, removed
  or re-pinned dependency (k-defense-kg #35: an "exact pin" changed which parser reads uploaded files); a new or
  stricter check (a CI test, a higher verify floor), since at worst it blocks wrongly and that shows; a new optional
  field in an API response.
- **high**: DB schema, data loads, a breaking API change (a field removed, renamed, retyped or given a new
  meaning), ground-truth or eval data and re-recorded expected outputs (a regression can hide in them), secrets, and
  anything that removes or loosens what a review, verify or merge gate requires (hhmode #9 and #13 loosened it). A
  change that both tightens and loosens a gate is high.

Below high, the change may merge without the user after the merge check (scripts/automerge.py; user decision
2026-10-30), unless the repo's CLAUDE.md says otherwise. High goes to the user, so a change that fits two tiers gets
the higher one.
