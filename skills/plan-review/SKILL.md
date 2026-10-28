---
name: plan-review
description: Pre-flight check of an implementation plan, delegated to one fresh-context plan-reviewer subagent that reads the repo and checks the plan's assumptions, order, verification and irreversible steps against the actual code. Not a design debate — open questions come back as small experiments to run, and the real adversarial review stays on the diff (code-review). Use whenever the user asks to "review my plan", "check this design", "plan 리뷰", "계획 리뷰해줘", "구현 전에 검토", "design review", or invokes /plan-review with or without a path argument. Always trigger this skill instead of reviewing directly — the agent that helped draft the plan rubber-stamps it.
---

# Plan Review

Check a plan against the repo before it is implemented. One fresh-context reviewer reads the
code and reports what is already wrong with the plan: false assumptions, broken order,
unverifiable steps, unguarded irreversible steps. It does not debate the design.

Why this narrow: adversarial review of a plan with no code behind it produces theoretical risks
and edge cases that never happen. Settle open questions by running something, then review what
got built (pstack `docs/guide/04-design.md`: "Don't spend reviewers on an abstract plan…
`/interrogate` belongs on a diff"). Here that is `/code-review`.

> **History.** 2026-07: Claude + Gemini pair. 2026-07-06: Gemini retired; two Claude personas
> (실무 실행자 / 회의적 아키텍트) given main-agent-picked files, a fixed Korean template with a
> praise section and an alternatives section, and a hand-built agreement map. 2026-10-28: cut to
> one repo-reading reviewer after pstack (`interrogate`, design guide) and the code-review
> redesign of 10-27: stated intent not questioned, evidence or silence, no "what if", open
> questions turned into experiments, "none" is valid.

## Procedure discipline

Copy Steps 1–4 into your todo list verbatim. A skipped step is marked `skip: <reason>`. The
report's first line is `PASS`, `ISSUES` or `BLOCKED` (Step 4), set from the reviewer's findings,
never from the main agent's own reading of the plan.

## Step 1 — Find the plan

Stop at the first match and announce the target in one line.

1. `$ARGUMENTS` names a file or contains the plan → that.
2. A plan, task list or design in the conversation → copy the most recent one **verbatim** (no
   summarizing: paraphrase softens the weak spots). Say which message it came from.
3. Nothing found → ask the user what to review.

A one- or two-file change with an obvious approach needs no plan review (pstack). Say so in one
line, then review anyway if the user invoked this skill.

## Step 2 — Gather material

- **Intent**: one paragraph — what the plan is for — from the request and the conversation.
  If the intent is unclear, ask the user first.
- **Plan**: the verbatim text from Step 1.
- **Repo path(s)** the plan touches.
- Do **not** pick files for the reviewer or pass your own concerns. It reads the repo itself; a
  reviewer handed a hypothesis tends to return it confirmed.

## Step 3 — Dispatch the reviewer

`Agent` with `subagent_type: plan-reviewer`; the prompt holds the Step 2 material and the report
language (the user's language). One reviewer: more reviewers on an abstract plan mostly add
invented risks. When the plan has irreversible steps, say so in the prompt.

## Step 4 — Report

- **ISSUES** — at least one blocker or should-fix.
- **PASS** — none.
- **BLOCKED** — no plan found, or the reviewer could not run.

Show findings as the reviewer wrote them; do not drop, soften or re-rank them (the main agent
wrote or accepted the plan, so its judgment is the biased one).

```
**Plan review: PASS | ISSUES | BLOCKED**

### Blockers
- [step] <title> — <why, one line> → <instead> (measured|inferred: <evidence>)
### Should fix
- ...
### Settle by running
- <question> → <experiment>
```

Raw reviewer output goes in an appendix only when the user asks.

## Follow-up

When the user disputes a finding, send the reviewer the finding and the user's point
(`SendMessage` to the same agent if it is still reachable, else a new `plan-reviewer` call with
the prior finding) and show its answer. After the plan is revised, review only the changed
parts. After the third round, stop: build it and review the diff.

## Common mistakes

- Reviewing in the main context, even partially → always delegate.
- Choosing files or passing suspicions to the reviewer → intent, plan and repo path only.
- Summarizing the plan before sending it → verbatim.
- Running several reviewers or rounds on a plan → one reviewer; settle the rest by running code.
- Telling the reviewer to always find something → "none" is a valid result.
