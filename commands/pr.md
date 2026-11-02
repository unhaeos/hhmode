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
3. **Commit.** One commit unless the user asked for more. Message: `<type>(<scope>): <what changed, in the repo's language>` followed by a blank line and 1 to 3 lines of why. When the task came from an issue, the body ends with `Closes #<n>` (one line per issue): the verifier finds the issue through it, and `automerge.py` closes it. Types: feat, fix, refactor, docs, test, chore. No `Co-Authored-By` trailer in commits and no "Generated with Claude Code" line in PR bodies (user decision 2026-10-29; `~/.claude/settings.json` sets `attribution` to empty strings).
4. **An independent verifier, not you, reviews and records.** Set the risk tier (low / medium / high) from the repo's CLAUDE.md; the change sets the tier, not the author. Run your own quick self-proof for what you touched (unit tests, typecheck). Then start a fresh verifier on the committed head **in the background** and wait for its notification:
   `bash ~/projects/hhmode/scripts/verify_fresh.sh <this worktree>`
   The script weighs what changed since the last reviewed commit on the branch (`scripts/review_weight.py`) and picks the review itself, then prints which and why: **carry** when only README.md, log.md or docs/ changed since a PASS (no session starts; the earlier record is carried over), **fix** for a small change (at most 150 lines, no new file: one verifier checks bug, verify and live on the diff since), **standard** for the first review, a large change or a new file (every lane, with Codex running alongside). Pass `standard` as a second argument only to force the full review. There is no separate review for a high tier: high goes to the user at the merge (step 8).
   A fix or standard review starts a new headless session that never saw the change being written (`skills/code-review/verifier.md`). That session runs the repo's verify step, the review lanes and a live lane, and writes the review record itself through `scripts/record_review.py`, which refuses records that overclaim. The script stops the session once its record is written. Only a verdict from an agent that did not write the code counts (pstack `shipping.md`): **for a gate, never run the `code-review` skill on your own change, and never write or edit `<sha>.review.md` or `<sha>.verify.json` yourself.**
   It prints the Review and Verify lines to paste into the PR body. On `ISSUES`, fix and run it again on the new head (at most three rounds), or open the PR with the verdict as it is and say why. Before the first push you may amend; after a push, every fix is a new commit. On `NO RECORD` or `BLOCKED`, read the reason it prints and fix that; do not work around it.
5. **Push.** `git push -u origin <branch>`. A task branch is pushed without asking (user decision 2026-10-28). Never push main, never `--force`.
6. **Open the PR.** Write the body to a temp file from `~/projects/hhmode/templates/pr.md`, every section filled (the same text is `.github/pull_request_template.md` for people on github.com). Acceptance criteria, Risk and Out of scope are the same fields as in the issue (`templates/issue.md`): list every criterion of every issue you close, each with how you checked it and the result. Verification keeps the Review and Verify lines exactly as `verify_fresh.sh` printed them, never typed by hand. Risk starts with `<low | medium | high> — <reason>`, the same line as the issue's; it is for the reader (the merge reads only the verifier's and Codex's tiers).
   Check the form first: fetch each closed issue with `gh issue view <n> --json body -q .body > <file>` and run `python3 ~/projects/hhmode/scripts/forms.py pr <tmp> --issue <n>=<file>` (one `--issue` per issue). Fix what it prints and run it again. Open the PR only on `ok`: `gh pr create --base main --title "<commit subject>" --body-file <tmp>`.

7. **Post the verifier's record on the PR.** `gh pr comment <number> --body-file <git common dir>/gate/<sha>.review.md` — the file the verifier wrote, unedited. The comment names the commit it reviewed; a later push makes it stale, and the next `/pr` run posts a new one.
   **Updating an open PR** (new commits after review fixes): re-run step 4 for the new head, then `gh pr edit <number> --body-file <tmp>` with the new `Review:`/`Verify:` lines **before** pushing, then push. A gated repo's CI ("리뷰·검증 관문") reads the body and is red while the lines name an older commit.
8. **Merge check.** Once CI has finished (`gh pr checks <number> --watch`), run `python3 ~/projects/hhmode/scripts/automerge.py <number>` from this worktree. Where the repo is listed in `~/projects/hhmode/local/merge_poll.json`, the local poller (`scripts/merge_poll.py`, a systemd user timer) also runs it within a few minutes of CI finishing; the two never clash.

   It holds a lock per PR, so only one merge check runs on a PR at a time, and it ends quietly on a PR that is no longer open. It first checks the facts for the reviewed commit: the verifier's review and verify are PASS, the Codex review ran on the branch's last standard review (a fix or carry round has none of its own), neither the verifier nor Codex rated the tier high (`skills/code-review/references/tiers.md`; your own `## Risk` line is for the reader and is not read), the PR is mergeable and CI is green, and where the repo uses the Codex app on GitHub, its security review has finished with no unresolved findings. Only then does it start the merge check, a fresh Claude that reads the PR, its issue, the repo's CLAUDE.md, the records, the Codex app's comments and the diff (`skills/code-review/merge-check.md`). On its yes, Claude itself runs the one merge command it is allowed (`gh pr merge ... --match-head-commit`, pinned to this PR and the reviewed commit); the script reads the PR back, runs the same command itself if Claude's did not run, closes the issue and comments the reason on the PR. Slack hears only what needs the user, once per commit: a high tier, the merge check's no, unresolved Codex findings, a failed merge. A fact you can fix (CI, review, conflict) is printed for you, not sent. It merges only while `~/projects/hhmode/local/automerge` says `on`.
9. **Stay with the PR until it merges or goes to the user.** You own this PR from build to merge (pstack `autopilot-full`: one owner carries each PR). When automerge.py did not merge, act on its reasons here:
   - CI failing, or the PR conflicts with main: fix it as a new commit (for a conflict, `git merge origin/main`; never rebase a pushed branch), run step 4 on the new head, push, post the new record (step 7) and run step 8 again.
   - Review ISSUES: fix the finding the same way, or leave it and say why in the PR.
   - Risk tier high, the merge check said no, or the Codex security review has unresolved findings: the script already told the user on Slack. Stop.
   - The Codex security review has not finished: nothing to fix. Wait, then look again as in step 8 (where the merge poller covers the repo, it looks again on its next pass). If no Codex comment appears on the PR, comment `@codex security review` to start it.
   - A lane BLOCKED for a reason you cannot fix, or three rounds without a merge: run `python3 ~/projects/hhmode/scripts/automerge.py <number> --report` yourself (also where the merge poller covers the repo; the lock keeps the two apart), which sends the reasons to Slack, and stop. The PR goes to the user (or `/land`).
10. **Report.** Print the PR URL, the verdict line, the automerge line (with the merge check's reason), and anything the user must look at first.

## Rules

- A PR with an empty or hand-waved Verification section is not opened. Run the check or write `BLOCKED` with the reason.
- Never `--force`, never push to main. This command merges only through `automerge.py` (step 8); any other merge is `/land` (the merge-owner session) or the user.
- If `gh` is not authenticated or the repo has no remote, stop and say so.
- Output in Korean; commit message and PR body in the repo's existing language.

## Args
$ARGUMENTS
