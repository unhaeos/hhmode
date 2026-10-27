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
4. **Verify before anything leaves the machine.** Set the risk tier (low / medium / high) from the repo's CLAUDE.md; the change sets the tier, not the author. If the repo has `scripts/verify.py`, run `python3 scripts/verify.py` on the committed tree — it picks and runs the checks CI cannot run and prints a block that starts with `**Verify: <verdict>** · <sha7>`; otherwise run the checks the repo's CLAUDE.md lists for the areas you touched. Then **always** run the `code-review` skill on the branch diff — standard mode, full mode when the tier is high. This is not optional and not left to memory: automatic review is what makes it work (Google: features users must remember to trigger "failed to scale"). Fix `ISSUES` and re-run (at most three rounds), or open the PR with the verdict as it is and say why. Every fix is a new commit: re-run verify and review for it — both records are per commit, and a gated repo's pre-push hook refuses a commit without them. Keep the review block for step 8.
5. **Confirm the push.** Show the branch name, the remote, and the commit list, then ask once: push and open a PR? Do not push before an explicit yes (global rule: confirm before `git push`).
6. **Push.** `git push -u origin <branch>`.
7. **Open the PR.** `gh pr create --base main --title "<commit subject>" --body-file <tmp>` with this body, every section filled:

   ```
   ## What
   <2 to 5 lines: what changed, from the user's point of view>

   ## Why
   <1 to 3 lines: the reason or the issue>

   ## Verification
   **Review: PASS | ISSUES | BLOCKED** · <sha7> · <mode>
   **Verify: PASS | FAIL | BLOCKED** · <sha7> · patch <id> · (copy the verify.py block as printed: this line, then its table)
   **Risk tier: low | medium | high**
   | Check | Command | Result |
   |---|---|---|
   | <tests / doctor / bench / smoke> | `<exact command>` | <exit code, key output line, or path to evidence file> |
   | Independent review | `code-review` skill (standard / full) | <review verdict · sha7 · what was fixed> |
   Label each result `measured` (you ran it) or `inferred`. If something could not be run, say so here, not nowhere.

   ## Risks
   <what could break elsewhere, and what you checked to rule it out; "none found" is allowed only with the check that found none>

   ## How to revert
   <one line: `git revert <sha>`, flag to flip, or the data restore step if the change wrote to a DB>

   ## Not in this PR
   <follow-ups deliberately left out>
   ```

8. **Post the review on the PR.** `gh pr comment <number> --body-file <tmp>` with the `code-review` report block from step 4. The comment names the commit it reviewed; a later push makes it stale, and the next `/pr` run posts a new one.
   **Updating an open PR** (new commits after review fixes): re-run step 4 for the new head, then `gh pr edit <number> --body-file <tmp>` with the new `Review:`/`Verify:` lines **before** pushing, then push. A gated repo's CI ("리뷰·검증 관문") reads the body and is red while the lines name an older commit.
9. **Report.** Print the PR URL, the verdict line, and anything the reviewer must look at first.

## Rules

- A PR with an empty or hand-waved Verification section is not opened. Run the check or write `BLOCKED` with the reason.
- Never `--force`, never push to main, never merge from this command. Merging is `/land` (the merge-owner session) or the user.
- If `gh` is not authenticated or the repo has no remote, stop and say so.
- Output in Korean; commit message and PR body in the repo's existing language.

## Args
$ARGUMENTS
