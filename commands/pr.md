---
description: Commit the current work, push the branch, and open a pull request whose body carries the verification evidence. Never pushes to main.
argument-hint: [one-line summary of the change] (optional; inferred from the diff if omitted)
---

# /pr

Turn the current branch into a reviewable pull request. One task, one branch, one PR.

## Steps

1. **Branch check.** `git rev-parse --abbrev-ref HEAD`. If it is `main` or `master`, stop: create a branch first (`git checkout -b <kebab-case task name>`) and tell the user which name you used. Never commit to or push main from this command.
2. **Working tree.** `git status --short`. Stage only files that belong to this task (`git add <paths>`, never `-A` blindly). List anything you left unstaged and why.
3. **Commit.** One commit unless the user asked for more. Message: `<type>(<scope>): <what changed, in the repo's language>` followed by a blank line and 1 to 3 lines of why. Types: feat, fix, refactor, docs, test, chore. Append `Co-Authored-By` as the session's attribution rules require.
4. **Confirm the push.** Show the branch name, the remote, and the commit list, then ask once: push and open a PR? Do not push before an explicit yes (global rule: confirm before `git push`).
5. **Push.** `git push -u origin <branch>`.
6. **Open the PR.** `gh pr create --base main --title "<commit subject>" --body-file <tmp>` with this body, every section filled:

   ```
   ## What
   <2 to 5 lines: what changed, from the user's point of view>

   ## Why
   <1 to 3 lines: the reason or the issue>

   ## Verification
   **Verdict: PASS | ISSUES | BLOCKED**
   | Check | Command | Result |
   |---|---|---|
   | <tests / doctor / bench / smoke> | `<exact command>` | <exit code, key output line, or path to evidence file> |
   Label each result `measured` (you ran it) or `inferred`. If something could not be run, say so here, not nowhere.

   ## Risks
   <what could break elsewhere, and what you checked to rule it out; "none found" is allowed only with the check that found none>

   ## Not in this PR
   <follow-ups deliberately left out>
   ```

7. **Report.** Print the PR URL, the verdict line, and anything the reviewer must look at first.

## Rules

- A PR with an empty or hand-waved Verification section is not opened. Run the check or write `BLOCKED` with the reason.
- Never `--force`, never push to main, never merge. Merging is the user's action in the PR view.
- If `gh` is not authenticated or the repo has no remote, stop and say so.
- Output in Korean; commit message and PR body in the repo's existing language.

## Args
$ARGUMENTS
