---
description: Commit the current work, push the branch, and open a pull request whose body carries the verification evidence. Never pushes to main.
argument-hint: [one-line summary of the change] (optional; inferred from the diff if omitted)
---

# /pr

Turn the current branch into a reviewable pull request. One task, one branch, one PR.

## Steps

1. **Branch check.** `git rev-parse --abbrev-ref HEAD`. If it is `main` or `master`, stop: create a branch first (`git checkout -b <kebab-case task name>`) and tell the user which name you used. Never commit to or push main from this command.
   If the repo's CLAUDE.md says agents work in worktrees, also confirm you are in one: `git rev-parse --git-dir` must differ from `git rev-parse --git-common-dir`. If not, stop and say so.
2. **Working tree.** `git status --short`. Stage only files that belong to this task (`git add <paths>`, never `-A` blindly). List anything you left unstaged and why.
3. **Commit.** One commit unless the user asked for more. Message: `<type>(<scope>): <what changed, in the repo's language>` followed by a blank line and 1 to 3 lines of why. Types: feat, fix, refactor, docs, test, chore. Append `Co-Authored-By` as the session's attribution rules require.
4. **An independent verifier, not you, reviews and records.** Set the risk tier (low / medium / high) from the repo's CLAUDE.md; the change sets the tier, not the author. Run your own quick self-proof for what you touched (unit tests, typecheck). Then start a fresh verifier on the committed head **in the background** and wait for its notification:
   `bash ~/projects/hhmode/scripts/verify_fresh.sh <this worktree> standard` (`full` when the tier is high)
   It starts a new headless session that never saw the change being written (`skills/code-review/verifier.md`). That session runs the repo's verify step, the review lanes and a live lane, and writes the review record itself through `scripts/record_review.py`, which refuses records that overclaim. Only a verdict from an agent that did not write the code counts (pstack `shipping.md`): **for a gate, never run the `code-review` skill on your own change, and never write or edit `<sha>.review.md` or `<sha>.verify.json` yourself.**
   It prints the Review and Verify lines to paste into the PR body. On `ISSUES`, fix and run it again on the new head (at most three rounds), or open the PR with the verdict as it is and say why. Before the first push you may amend; after a push, every fix is a new commit. On `NO RECORD` or `BLOCKED`, read the reason it prints and fix that; do not work around it.
5. **Push.** A task branch is pushed without asking (user decision 2026-10-28). Never push main, never `--force`.
6. **Push.** `git push -u origin <branch>`.
7. **Open the PR.** `gh pr create --base main --title "<commit subject>" --body-file <tmp>` with this body, every section filled:

   ```
   ## What
   <2 to 5 lines: what changed, from the user's point of view>

   ## Why
   <1 to 3 lines: the reason or the issue>

   ## Verification
   <the Review line and the Verify block exactly as verify_fresh.sh printed them — never typed by hand>
   **Risk tier: low | medium | high**
   | Check | Command | Result |
   |---|---|---|
   | <your self-proof: tests / typecheck> | `<exact command>` | <exit code, key output line> |
   | Independent verifier | `verify_fresh.sh` (standard / full) | <verdict · sha7 · verifier session id · record path> |
   Label each result `measured` (you ran it) or `inferred`. If something could not be run, say so here, not nowhere.

   ## Risks
   <what could break elsewhere, and what you checked to rule it out; "none found" is allowed only with the check that found none>

   ## How to revert
   <one line: `git revert <sha>`, flag to flip, or the data restore step if the change wrote to a DB>

   ## Not in this PR
   <follow-ups deliberately left out>
   ```

8. **Post the verifier's record on the PR.** `gh pr comment <number> --body-file <git common dir>/gate/<sha>.review.md` — the file the verifier wrote, unedited. The comment names the commit it reviewed; a later push makes it stale, and the next `/pr` run posts a new one.
   **Updating an open PR** (new commits after review fixes): re-run step 4 for the new head, then `gh pr edit <number> --body-file <tmp>` with the new `Review:`/`Verify:` lines **before** pushing, then push. A gated repo's CI ("리뷰·검증 관문") reads the body and is red while the lines name an older commit.
9. **Report.** Print the PR URL, the verdict line, and anything the reviewer must look at first.

## Rules

- A PR with an empty or hand-waved Verification section is not opened. Run the check or write `BLOCKED` with the reason.
- Never `--force`, never push to main, never merge from this command. Merging is `/land` (the merge-owner session) or the user.
- If `gh` is not authenticated or the repo has no remote, stop and say so.
- Output in Korean; commit message and PR body in the repo's existing language.

## Args
$ARGUMENTS
