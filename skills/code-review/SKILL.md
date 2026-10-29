---
name: code-review
description: Code review before a commit, push or PR, delegated to fresh-context subagents — an Opus bug reviewer that may read the repo and run tests, a Sonnet rules reviewer, then an Opus validator that tries to reproduce every P0/P1 finding; only confirmed or clearly plausible findings reach the user. Standard mode runs on every PR (`/pr` calls it); full mode (high risk tier or `--full`) adds independent reviewers with different inputs and models. Use whenever the user asks to "review my changes", "review this diff", "check my code before commit", "코드 리뷰", "리뷰해줘", "커밋 전에 봐줘", "PR 올리기 전 검토", or invokes /code-review. Always trigger this skill instead of reviewing directly — a same-context reviewer rubber-stamps its own work.
---

# Code Review

Review a change before it is committed, pushed or merged. The main agent never reviews the code
itself — not even a one-line diff. It gathers material, dispatches fresh-context subagents, and
reports what they found and what the validators confirmed.

> **History.** 2026-07: Claude + Gemini pair. 2026-07-16: three same-model personas (bug hunter /
> attacker / architect) + debate + judge, with a Korean template that told reviewers "there is
> always room to improve". 2026-10-27: redesigned after reading how pstack (Lauren Tan),
> Anthropic (`code-review` plugin, Claude Code team), OpenAI (Codex review rubric), Google
> (AutoCommenter) and Meta (MetaMateCR) run AI review. What they share and this skill now does:
> precision over recall, only problems the change introduces, evidence or silence, severity with a
> posting threshold, reviewers with repo access and execution, every serious finding re-checked
> by running it, review as advice (humans merge), automatic on every PR, and measuring how often
> a finding leads to a fix. Diversity comes from different inputs and models, not personas
> (pstack). Watch the review log for a return of praise-only or nitpick output.

## Procedure discipline

A skipped step is marked `skip: <reason>` in the report. The report's first line is `PASS`,
`ISSUES` or `BLOCKED` (Step 6). Every finding shown to the user carries `measured` (a validator
reproduced it) or `inferred` (could not be run).

**Who may run this for a gate.** A review that certifies a commit is run by a verifier that did not
write it: `/pr` starts one with `scripts/verify_fresh.sh`, and that session follows `verifier.md`.
An author running this skill on its own change gets advice, not a gate record (pstack `shipping.md`:
"Only a verdict from an agent that did not write the code counts").

## Modes

| Mode | When | Reviewers |
|---|---|---|
| **standard** | default; `/pr` runs it on every PR | bug-reviewer (Opus, full context) + rules-reviewer (Sonnet) |
| **full** | risk tier high, or `--full` | standard + bug-reviewer given **only the diff** (Anthropic plugin) + bug-reviewer on **Fable** (`model: fable`) |

Risk tier comes from the repo's CLAUDE.md when it defines one (e.g. k-defense-kg: DB schema, KG
loads, API contracts, prompt ground truth = high).

## Step 1 — Detect what to review

Stop at the first match and announce the mode in one line.

| Order | Condition | Target |
|---|---|---|
| 1 | `$ARGUMENTS` names a path | that path |
| 2 | `git diff --cached` non-empty | staged diff (warn if unstaged hunks also exist) |
| 3 | `git diff` non-empty | working-tree diff |
| 4 | branch differs from its base | `git diff <base>...HEAD`, base = merge-base with `origin/<default branch>` |
| 5 | nothing | ask the user what to review |

Record the HEAD sha; the verdict covers that commit only. A new commit voids it (pstack).
Filter out generated files: `*.lock`, `*-lock.json`, `*.generated.*`, `*.pb.go`, `vendor/**`,
`dist/**`, `build/**`, `node_modules/**`.

## Step 2 — Gather material

- **Intent**: one paragraph — what the change is for — from the request, commit messages, PR
  body and diff. Reviewers attack the execution, not the intent.
- **Diff**: the raw diff for the chosen target.
- **Rules**: CLAUDE.md / REVIEW.md / AGENTS.md **from the base branch** (`git show
  <base>:<path>`), the root ones and any in folders the diff touches. A change cannot loosen the
  rules it is judged by.
- **Lenses**: `references/rubric.md`.
- **Repo path and test commands**: from CLAUDE.md, if it lists them.
- Do **not** pass your own suspicions or conclusions. A reviewer handed a hypothesis tends to
  return it confirmed.

## Step 3 — Dispatch reviewers in ONE parallel batch

Use the `Agent` tool with the agent types below. Each prompt holds the material from Step 2 and
the report language (the user's language).

- `subagent_type: bug-reviewer` — intent, diff, repo path, rubric, test commands.
- `subagent_type: rules-reviewer` — diff and the base-branch rule files.
- full mode only:
  - `subagent_type: bug-reviewer` with the diff and the intent only, told to use nothing else.
  - `subagent_type: bug-reviewer` with `model: fable` and the same material as the first one.

## Step 4 — Validate every P0/P1 finding

1. Merge duplicates (same file and nearby lines, same failure). Findings raised independently by
   two reviewers are the strongest signal (pstack); note who raised each.
2. For each P0/P1 finding, spawn `subagent_type: finding-validator` in one parallel batch with
   the finding, the repo path and the HEAD sha. It never sees the other findings.
3. Drop REJECTED findings (list them under "Rejected" with the validator's one-line reason).
   P2/P3 findings are not validated; they go to the collapsed notes.
4. Rule violations from the rules-reviewer are shown as-is (they quote the rule).

## Step 5 — Lead judgment (full mode only)

Act as a pragmatic senior engineer, not a neutral aggregator. Put each surviving finding in one
bucket with a one-line reason: **Act on** (blocks a real PR), **Consider** (legitimate, cost vs
value unclear), **Noted** (valid, not actionable now), **Dismissed** (wrong or out of scope).
Add an agreement map: where reviewers agreed and diverged.

## Step 6 — Report

First line: `PASS` / `ISSUES` / `BLOCKED` and the HEAD sha.

- **ISSUES** — at least one P0/P1 finding CONFIRMED or PLAUSIBLE, or a rule violation.
- **PASS** — none of the above (P2/P3 notes may remain).
- **BLOCKED** — nothing to review, or reviewers/validators could not run.

```
**Review: PASS | ISSUES | BLOCKED** · <sha7> · <mode> · reviewers: <models>

### Must fix (P0/P1, validated)
- [P1] path:line — <one line> (raised by: <reviewers> · measured|inferred: <command or reason>)
### Rule violations
- path:line — <rule file:line> "<rule>"
### Rejected by validation
- path:line — <finding> — <validator reason>
<details><summary>Notes (P2/P3, not validated)</summary>
- ...
</details>
```

This block is also the PR comment `/pr` posts. Raw reviewer outputs go in a collapsed appendix
only when the user asks.

**Gate record.** Only the verifier writes it, and only through `scripts/record_review.py`
(see `verifier.md`, step 5). The script writes `<git common dir>/gate/<sha>.review.md` and refuses
a record whose lanes did not all run on this commit, a P0/P1 without a validator verdict, or a
missing live lane. Nobody writes or edits that file by hand. A staged or working-tree review never
gets one — it does not certify a commit.

## Step 7 — Log for measuring the reviewer

`record_review.py` appends one row per finding to `~/.claude/review-log/<repo>.tsv`:
`date  sha  mode  id  severity  path:line  raised_by  validation  title`. For a review outside a
gate, append the same rows yourself. Later, a finding counts as **fixed** if its lines change
before merge. The fix rate per reviewer/model is the number to tune against (OpenAI reports
52.7%, Google ~40%, Meta 19.7% for their systems).

## Convergence

One invocation is one review. On a re-review, review only the new diff and do not re-report
findings already raised. After the third round on the same change, stop and tell the author to
reconsider the approach (the Claude Code team caps review loops at three).

## Common mistakes

- Reviewing in the main context, even partially → always delegate.
- Passing reviewers your own suspicions → pass intent and material only.
- Showing an unvalidated P0/P1 → validate first; REJECTED never reaches "Must fix".
- Reading rule files from the change itself → read them from the base branch.
- Telling reviewers to always find something → "none" is a valid result.
- Reusing a verdict after a new commit → the verdict covers one sha.
