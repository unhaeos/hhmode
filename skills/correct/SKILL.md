---
name: correct
description: Find the mistakes agents keep repeating in a repo (or in this harness) and make each one impossible instead of writing another rule. Reads review-log, log.md, git history and the rule files; a mistake class counts once it has happened twice; fixes at the highest level that works (architecture, then types, then a lint or check whose error names the fix, then a test, docs last) and proves each new check fails on a real past mistake. Use for /correct, "같은 실수 반복", "왜 자꾸 이래", "실수 패턴 찾아", or after the user corrects the agent.
---

# Correct

The user keeps correcting agents for the same mistakes. Change the repo or the harness so the next agent
cannot make them. Assume every contributor is an agent that sees only the files it opened, copies the nearest
example, and takes the shortest path that works; design so that a change that looks right from one file is
right everywhere.

Target: the repo the user names (default: the current one), plus this harness (`~/projects/hhmode`) when a
class lives in a skill, command or principle.

## 1. Find the mistake classes

Read, for the target:

- **review-log**: `~/.claude/review-log/<repo>.tsv` — every finding a reviewer raised, with severity and fate.
- **log.md**: `~/projects/hhmode/log.md` — incidents the user or an agent wrote down.
- **git history**: `git log --since=<window, default 30 days>`: `fix:` commits, reverts (`Revert`, `git log
  --grep=revert -i`), commits that touch the same lines twice, and messages that say "again" or "still".
- **rule files**: the repo's CLAUDE.md / AGENTS.md / REVIEW.md, `~/.claude/CLAUDE.md`, and the hhmode skills
  and commands (a rule that is text only is a candidate: nothing fails when an agent skips it).
- Optionally, recent session transcripts (`~/.claude/projects/<repo slug>/*.jsonl`) for the user's own
  corrections ("아니", "먼소리야", "왜 또", a repeated instruction). Read only the target repo's transcripts.

Group the mistakes into classes by cause, not by symptom. **A class counts once it has happened twice.** Cite
every occurrence (sha, review-log row, log.md line, or transcript line).

## 2. Fix each class at the highest level that works

1. **Eliminate it with architecture.** One owner per piece of state, one supported way per task. Hide internals
   so the wrong use fails. Replace hand-synced lists with one source of truth. Delete the old way and dead code
   an agent would copy.
2. **Make the bad state unwritable.** Types first. If bad code still passes, add a lint, hook or CI check whose
   error names the file, function or command to use instead. If the pattern is already common in the repo, fail
   only when a change **adds** more (check the added lines, not the whole tree).
3. **Test the behavior.** Fix or delete a test that still passes when the behavior breaks, or fails when only
   internals change.
4. **Docs or agent rules last, only for judgment calls** — nothing fails when an agent skips them. If the class
   needs judgment, make the rule prominent and quote the real failure next to it.

A harness class (a skill tells agents to do something they cannot or will not do) is fixed in the skill itself:
remove an unexecutable step, or turn a step that gets skipped into a script the next step depends on.

## 3. Prove and propose

For each class, before changing anything:

- The proof needs a session that can write and run code in a worktree (a scratch check, an old sha checked out).
  A read-only run reports each proof as `BLOCKED` and names the exact command that would prove it; it does not
  count the class as proven. (First run, 2026-10-29: every proof was BLOCKED in a read-only session.)
- Write the check, then **show it fails on the real past mistake** (check out the old sha, or replay the old
  input) and passes on the fixed code. A check that has never caught anything is not proof.
- Run the same command locally and where CI runs it.
- Exceptions go on the offending line with a reason, an expiry date and the user's approval.

Then present, per class: the evidence (all occurrences), the level you picked and why a higher level did not
work, the change, and the proof output. **Wait for the user's approval before applying** — a structural change
affects every agent working in that repo. Apply approved changes as one commit per class through `/pr`.

## 4. Keep the rule table

Keep a table in the target's agent instruction file (the repo's CLAUDE.md; for this harness, the README) that
pairs each rule with what enforces it:

| Rule | Enforced by | Evidence |
|---|---|---|
| <the rule> | <script / hook / lint / test, or "nothing"> | <log.md line, sha, review-log row> |

When the user corrects an agent, fix the mistake and add the rule. If the rule was already in the table and its
enforcer is "nothing", that is a repeat: fix it at the highest level in the same change. Drop a rule once its
mistake can no longer happen.

## Reply

Verdict line first (`PASS` = no class at two or more occurrences, `ISSUES` = classes found, `BLOCKED` = could not
read the sources). Then each class with its evidence, the level picked and why a higher level did not work, the
proposed change and its proof, and which ones wait for approval. Label each claim `measured`, `inferred` or
`guess`.

Adapted from pstack `correct` (Lauren Tan, MIT; `cursor/plugins/pstack`, c742dd6). Added: review-log and log.md as
inputs, harness classes, the propose-then-approve step. pstack's `reflect` (transcript mining with three
reviewer lenses) is folded into step 1's optional transcript read rather than ported whole.
