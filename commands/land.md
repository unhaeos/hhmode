---
description: Merge one reviewed PR into main — one at a time, on top of current main, CI green, risk tier respected. For the merge-owner session only.
argument-hint: <PR number>
---

# /land

Land a pull request that `/pr` opened. One PR at a time: do not start the next until main has the previous one.

## Steps

1. **Read the PR.** `gh pr view <n> --json number,title,url,headRefName,baseRefName,isDraft,mergeable,mergeStateStatus,body`. Stop if the base is not `main`, the PR is a draft, or it is not mergeable.
2. **Evidence.** The body must have a Verification section with a `PASS` verdict, an `Independent review` row from a reviewer that did not write the code, and a `## Risk` section that starts with `<low | medium | high> — <reason>` (older bodies: a `Risk tier` line). If any is missing, stop and report what is missing. An `ISSUES` or `BLOCKED` verdict is not landed.
3. **Tier.**
   - `low`: land without asking only if the repo's CLAUDE.md grants that for low tier.
   - `medium` / `high`, or no such grant: show the title, tier, verdict and diff stat, then ask the user once. An agent's approval never stands in for the user's.
4. **On top of current main.** If `mergeStateStatus` is `BEHIND`, run `gh pr update-branch <n> --rebase` and wait for CI again. If the rebase conflicts, stop: the author's worktree resolves it, not the merge owner. In a gated repo a clean rebase usually keeps the review/verify gate green (the `Verify:` line's patch id still matches the change). It turns red when the diff text differs: the change itself, or a line main changed within three lines of it (the id includes context lines on purpose — a false red costs a re-run, a false green certifies unchecked code). Either way stop and send it back to the author for a new `/pr` round on the rebased head.
5. **CI.** `gh pr checks <n> --watch --fail-fast`. Every check green, or stop and report the failing one. CI green is required but is not the verdict; the verdict is the evidence in step 2.
6. **Merge.** `gh pr merge <n> --squash --delete-branch`. Then read the PR back (`gh pr view <n> --json state,mergeCommit`) — a merge queue may only have queued it.
7. **After.** In the main checkout, `git pull --ff-only`. Remove the task's worktree if it is clean (`git worktree remove <path>`); if it has leftover work, list it and leave it.
8. **Report.** Merged commit SHA, PR URL, tier, and anything left behind.

## Rules

- Never `--admin`, never `--force`, never bypass a failing check.
- A fix after merge is a new PR on top. Never rewrite merged history.
- Output in Korean.

## Args
$ARGUMENTS
