Risk tier. The change sets it, not the author. When unsure, take the higher one.

- **low**: only docs, comments, tests, or scripts nothing else imports (an experiment script, a test fixture).
  Nothing a user, another program or an agent sees behaves differently.
- **medium**: any behaviour change in code, prompts, skills, commands, agents, UI or tooling; any added, removed
  or re-pinned dependency (k-defense-kg #35: an "exact pin" changed which parser reads uploaded files).
- **high**: DB schema, data loads, API contracts, ground-truth or eval data, secrets, and anything that changes
  what a review, verify or merge gate requires or allows (hhmode #9 loosened the review gate).

Below high, the change may merge without the user after the merge check (scripts/automerge.py; user decision
2026-10-30), unless the repo's CLAUDE.md says otherwise. High goes to the user, so a change that fits two tiers gets
the higher one.
