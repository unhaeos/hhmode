# hhmode

A small, git-tracked agent harness shared by Claude Code and Codex. Everything here is plain text except `scripts/`; each tool reads it through a symlink into the directory it already scans. Nothing runs on its own.

Modeled on [pstack](https://github.com/cursor/plugins/tree/main/pstack) by Lauren Tan (it moved from `poteto/pstack` into Cursor's plugins repo; local copy for reading: `~/ref/pstack-src/pstack`), deliberately kept to the parts that have earned their place. A rule gets added here only after the same failure has shown up twice.

## Layout

```
skills/        One SKILL.md per skill. Symlinked into ~/.claude/skills/<name> and ~/.codex/skills/<name>.
agents/        Subagent definitions (reviewers). Symlinked into ~/.claude/agents/<name>.md.
commands/      Claude Code slash commands (Claude Code only). ~/.claude/commands -> this folder.
templates/     The two forms a task passes through: issue.md and pr.md (copied to .github/ for github.com).
principles/    One principle per file. Skills reference them by absolute path.
scripts/       Checks the harness runs instead of trusting text: forms.py, verify_fresh.sh, review_weight.py, record_review.py, codex_review.py, automerge.py, sync_self.sh (+ tests).
log.md         Failure log, one line per incident.
local/         Machine-local values (identity, paths). Gitignored.
```

Not here yet, added when a need appears: a router, per-repo `features/` maps.

## Forms

A task passes through four linked forms, and the three fields they share keep the same names, so what the issue asks for is checked again at every step:

| Form | Where | Shared fields |
|---|---|---|
| Issue | `templates/issue.md` (also `.github/ISSUE_TEMPLATE/task.md`); `/issue` writes and opens it | **Acceptance criteria** (numbered `AC1`, `AC2`, ...), **Risk** (`low`, `medium` or `high` plus a reason), **Out of scope** |
| PR body | `templates/pr.md` (also `.github/pull_request_template.md`); `/pr` step 6 | the same three: every criterion of every closed issue is listed with how it was checked; its Risk section starts with the same `<tier> — <reason>` line as the issue's (for the reader; the merge reads only the verifier's and Codex's tiers) |
| Verifier record | `scripts/record_review.py` | a verdict, with evidence, on each criterion of the issue; a criterion that is not met makes the review ISSUES |
| Merge check | `skills/code-review/merge-check.md` | a criterion that is not met or unclear, or a change the issue puts out of scope, sends the PR to the user |

`scripts/forms.py` is the one parser and checker: `python3 scripts/forms.py issue FILE` and `python3 scripts/forms.py pr FILE --issue N=FILE` print one problem per line, or `ok`. `/pr` runs it before opening a PR, and `automerge.py` runs it as one of its facts. The issue comes to the verifier through `Closes #<n>` in a commit message; an issue it cannot read stops `verify_fresh.sh`. Tests: `python3 -m unittest scripts/test_forms.py`; one test fails when a `.github` template drifts from `templates/`.

## Independent verification

The author of a change does not review it for a gate. `/pr` runs `scripts/verify_fresh.sh`, which starts a fresh headless session at the same commit; that session follows `skills/code-review/verifier.md` (verify step, review lanes, a live lane on the real surface) and writes the record through `scripts/record_review.py`. The script decides the verdict and refuses a record whose lanes did not all run on this commit, a P0/P1 without a validator verdict, a live lane without evidence, or an acceptance criterion of the closed issue with no verdict; it also appends the review-log rows. The record opens with a summary table (verdict, risk, tests, live run, findings, criteria met). Tests: `python3 -m unittest scripts/test_record_review.py`.

**Review is proportional to what changed** (pstack `autopilot-full`: a rebase, a merge-conflict resolution or a minor fix gets a single verifier at the new head, and a wording-only change gets none). `scripts/review_weight.py` compares the commit with the newest earlier one on the branch that a verifier reviewed, and `verify_fresh.sh` prints which of three it chose and why:

| Weight | When | What runs |
|---|---|---|
| **carry** | only README.md, log.md or docs/ changed since a review that passed | nothing: `record_review.py --carry` writes the new record from the old one (first line `carry`), with no verifier session |
| **fix** | at most 150 lines changed (added + deleted; a first guess to tune from the review log) and no new file | one verifier, lanes `bug`, `verify` and `live`, on the diff since the reviewed commit; no rules lane, no Codex |
| **standard** | the first review on a branch, a larger change, a new file or a binary change | every lane: `bug`, `rules`, `bug-gpt` (Codex), `verify`, `live` |

The Codex reviewer (a second company's model, since a same-family reviewer shares the author's blind spots) starts in the background at the same time as the verifier instead of before it, and answers in JSON (`skills/code-review/gpt-review.schema.json`, rendered by `scripts/codex_review.py`) so its risk tier is always in the form the merge reads. The verifier waits for it before recording. There is no Fable reviewer and no `full` mode any more: every P0/P1 Fable raised was also raised by Opus, and it costs tokens (user decision 2026-10-30); old records that say `full` still count like standard. A headless verifier can stay open long after it has written its record, so the launcher stops it 30 seconds after the record appears (and after `VERIFIER_TIMEOUT`, default 3600 seconds, if there is none). Automerge asks for a Codex review on every standard record, and accepts fix and carry records on top of one. Tests: `python3 -m unittest scripts/test_review_weight.py scripts/test_codex_review.py`.

## Push gate

In a repo that turns it on, a branch is pushed only when its tip has a verifier record: `githooks/pre-push` runs `scripts/push_gate.py`, which needs `<git common dir>/gate/<sha>.review.md` (written only by `record_review.py`). Any review verdict passes, so `/pr` can still open a PR with ISSUES and say why; a verify FAIL does not. Branch deletes, tags and commits already on the remote's main pass. Turn it on with `git -C <repo> config core.hooksPath ~/projects/hhmode/githooks`; that replaces the repo's `.git/hooks`. On in hhmode itself. k-defense-kg keeps its own gate (`scripts/githooks`, which also checks file rules). Tests: `python3 -m unittest scripts/test_push_gate.py`.

## Auto-merge

`/pr` ends with `scripts/automerge.py <PR#>` once CI has finished. For a repo in `local/merge_poll.json`, the merge poller (below) also starts it within a few minutes of CI finishing. **One run per PR at a time:** the script holds an exclusive lock on `<git common dir>/gate/merge-<owner>-<repo>-<n>.lock` for the whole run and reads the PR fresh after taking it, so a second run waits, and a PR that is no longer open ends quietly (printed, no Slack). Two starters (`/pr` and the poller; before them a runner) could otherwise each start a merge check on one PR, each with its own Claude (verifier on k-defense-kg caf3607).

Facts first, for the reviewed commit: the verifier's review and verify are PASS, the Codex review ran on the branch's last standard review (a fix or carry round has none of its own), neither the verifier nor Codex rated the tier high (the author's `## Risk` line is for the reader: it is free text and the author wants the merge) (`skills/code-review/references/tiers.md`), the PR is open into main, mergeable and green, and the PR body fills the PR form and names every acceptance criterion of the issues it closes (`scripts/forms.py`). Any fact that fails stops it there, and the author fixes it.

**The Codex security review on GitHub** is a fact where the repo uses the Codex app (login `chatgpt-codex-connector[bot]`). The repo uses it when the PR, or any of the repo's 10 most recent PRs, has a comment containing `codex-review-state:v1`, so there is no list of repos. The app edits one PR comment whose HTML comment carries its state as JSON; only that JSON, from the app's own login, is read, never the prose. If the PR's `security_review` status is not `completed`, the script prints "the Codex security review has not finished" (not sent to Slack; the runner starts again when the comment is edited, and the app reviews when a PR is opened for review, a draft is marked ready, or someone comments `@codex security review`). If `has_unresolved_findings` is true, the PR goes to the user on Slack. A review of an earlier commit than the head still counts, and the merge check is told so. The app's comments, review bodies and line comments go to the merge check, which says no to a finding the change neither fixes nor explains.

Then the merge check: a fresh headless Claude reads the PR, the issues it closes, the repo's CLAUDE.md, the records (with their criteria), the Codex app's comments and the diff (`skills/code-review/merge-check.md`) and answers merge or not with a reason in plain English; a repo rule that sends the change to the user wins, and so does a criterion that is not met or unclear. **Claude runs the merge itself** (user decision 2026-11-02): in mode `on` it is given Bash and an allowlist of exactly one command, `gh pr merge <n> -R <owner>/<repo> --squash --match-head-commit <reviewed sha>`, and runs it once on a yes; an exact entry pins the PR and the commit (measured: the entry for PR 17 ran, the same command for PR 16 was denied). Dry-run and any mode other than `on` give it no tools and no command. The script then reads the PR back: merged means "merged by the merge check (Claude)"; still open means the command did not run, so the script runs the same command itself and the PR comment says so, which leaves no approved PR unmerged by a denied tool. It then closes the issues the PR closes if GitHub left them open and comments the reason on the PR.

Slack (`local/notify.json`: `{"token_file": ..., "channel": ...}`) hears every merge (a "Merged" DM; `/land` sends the same through `scripts/notify_merge.py`, hhmode #18) and what needs the user: a high tier, the merge check's no, unresolved Codex findings, a failed merge or issue close, or `--report` from an author that gave up after three rounds. **The same message for the same PR head is sent once:** a marker file `gate/slack-<n>-<sha>.sent` keeps a hash of each message sent (CI and Gate both finishing starts the runner twice per push; a high-tier PR got "Needs you" twice). `local/automerge` = `on` merges; anything else reports what it would have done ("would merge, not merged"). Messages and PR comments are in plain English. Tests: `python3 -m unittest scripts/test_automerge.py`.

## Merge poller

`scripts/merge_poll.py` runs the merge check from this PC on a systemd user timer (every `interval_minutes`, default 3), for the repos in `local/merge_poll.json` (`{"repos": [{"repo": "<owner>/<name>", "path": "~/projects/<name>"}], "interval_minutes": 3}`). Each pass lists the open PRs and runs `automerge.py` for those that are ready: not a draft, CI finished and passed, a review record for the head on this machine, the Codex app's review finished where the repo uses it, and nothing sent yet for that head (automerge's once-per-head marker). It reads only data from GitHub (PR numbers, head SHAs, check and Codex states); no code GitHub serves runs here. It does nothing while `local/automerge` is not `on`. `python3 scripts/merge_poll.py --install` writes and starts the timer, `--uninstall` removes it, `--dry-run` says what one pass would run. Tests: `python3 -m unittest scripts/test_merge_poll.py`.

Why not a self-hosted runner: k-defense-kg #73 ran the merge check from a repository-level runner on this PC. The Codex security review of #73 (P1) and GitHub's hardening guide ("any user capable of invoking workflows has access to this environment") both apply: four accounts can push there, and a workflow on any branch naming the runner would run as this user next to the GitHub admin token, the Claude and Codex logins, the Slack token and the DB credentials, with the user in the docker group. The merge check needs exactly those credentials, so the runner was stopped (2026-11-02) and the check moved to a poller that GitHub sends no code to.

## Install (new machine)

```
git clone git@github.com:haehoonseo/hhmode.git ~/projects/hhmode
for s in ~/projects/hhmode/skills/*/; do ln -sfn "$s" ~/.claude/skills/$(basename "$s"); done
for s in hillclimb investigate; do ln -sfn ~/projects/hhmode/skills/$s ~/.codex/skills/$s; done
ln -sfn ~/projects/hhmode/commands ~/.claude/commands
git -C ~/projects/hhmode config core.hooksPath ~/projects/hhmode/githooks
for a in ~/projects/hhmode/agents/*.md; do ln -sfn "$a" ~/.claude/agents/$(basename "$a"); done
```

Then register `scripts/sync_self.sh` as a SessionStart hook in `~/.claude/settings.json`, so a merged PR reaches every new session without a manual pull: the checkout fast-forwards to `origin/main` (only on a clean `main`) and new skills and agents get their links. It prints one line when it changed something. Tests: `python3 -m unittest scripts/test_sync_self.py`.

```json
"SessionStart": [{"hooks": [{"type": "command", "timeout": 15,
  "command": "sh -c '[ -f \"$HOME/projects/hhmode/scripts/sync_self.sh\" ] || exit 0; exec bash \"$HOME/projects/hhmode/scripts/sync_self.sh\"'"}]}]
```

The `[ -f ] || exit 0` wrapper keeps a missing script from breaking session start (same as k-defense-kg's hooks).

Machine-local values go in `local/` (gitignored); see `commands/*.md` for what they read.

## Usage

Nothing to start. The symlinks make every skill available in any directory where Claude Code or Codex runs.

| Situation | Type |
|---|---|
| Improve one metric toward a target | `/hillclimb <metric> to <target>` |
| Find out why something happens, read-only | `/investigate <question>`, or just ask "why does X ..." |
| Review staged changes before a commit | `git add ...` then `/code-review` |
| Write and open an issue from the form | `/issue <what needs doing>` |
| Open a PR from a task worktree, with evidence | `/pr` |
| Merge one reviewed PR (merge-owner session) | `/land <PR#>` |
| Stress-test a plan before implementing | `/plan-review <path to plan>` |
| Write up results as a document | ask for a report; the `report` skill loads on its own |
| The last reply was hard to follow | `/bro`, or `/bro <the part>` |
| Memo, to-do collection, weekly report, DM draft | `/mm`, `/collect-todos`, `/weekly-report`, `/slack-dm` |

In Codex, `$hillclimb` and `$investigate` are available; the other skills depend on Claude Code tools.

While using it: when the agent gets something wrong, or you repeat an instruction, add one line to `log.md`. That log is the only input to this repo's growth.

## Three rules

Where the model reads them: rules 2 and 3 live in `~/.claude/CLAUDE.md` (loaded every session); rule 1 lives in each skill's *Procedure discipline* section. This README is for humans.

1. A skipped playbook step is marked `skip: <reason>`.
2. Verdict words are fixed. Work: `PASS / ISSUES / BLOCKED`. Investigation: `VERIFIED / NOT VERIFIED / INCONCLUSIVE`. Inconclusive is not a pass.
3. Every claim is labeled `measured` (ran it), `inferred` (follows from evidence), or `guess` (no evidence).

## Operating loop

- Every skill report starts with its verdict line. A judge or critic never confirms a finding without running it; unrunnable items are labeled `inferred`.
- When the agent gets something wrong, add one line to `log.md`.
- When the same line appears twice, promote it to a file (skill or principle) or a script.
- Every rule should point at a `log.md` entry that shows the failure it prevents. Rules without one get deleted.
- Rules that models no longer need also get deleted.

## Tool support

| Item | Claude Code | Codex |
|---|---|---|
| `hillclimb`, `investigate` | yes | yes |
| `code-review`, `plan-review` | yes (spawns subagents via the Agent tool) | no |
| `correct` | yes | finding only (applying a fix goes through `/pr`, a Claude Code command) |
| `report` | yes (uses the Artifact tool) | no |
| `commands/*` | yes | no |

## Skills

| Skill | Purpose |
|---|---|
| `hillclimb` | Iterative improvement of one metric: fixed stop predicate, frozen measurement harness, one hypothesis per iteration, keep or revert, `decision.tsv`. |
| `investigate` | Read-only investigation ending in a cited explanation or recommendation. |
| `code-review` | Opus bug reviewer (repo access, may run tests) + Sonnet rules reviewer; every P0/P1 re-checked by an Opus validator that tries to reproduce it; runs on every PR via `/pr`; a GPT reviewer (Codex) alongside, in the gate's standard review; a re-review reads only the diff since the last reviewed commit, sized by `scripts/review_weight.py` (carry, fix or standard). |
| `plan-review` | One repo-reading reviewer checks the plan's assumptions, order, verification and irreversible steps against the code; open questions come back as experiments. No design debate (pstack: review the diff, not the plan). |
| `report` | House style for written reports as HTML artifacts. |
| `correct` | Find mistakes agents keep repeating (review-log, log.md, git history, rule files, optionally transcripts); a class counts at two occurrences; fix at the highest level that works and prove the check fails on a real past mistake; propose, then apply after approval. |

## Taken from pstack

Source: pstack v0.15.32, MIT. Each adapted file notes its origin at the bottom.

| Here | pstack original | Changed |
|---|---|---|
| `skills/hillclimb` | playbook `hillclimb` | Removed Cursor subagent/model routing, worktree fan-out, PR steps. Added a prior-work check as step 1. |
| `skills/investigate` | playbook `investigation`, skill `figure-it-out` | Removed how/why/unslop routing. Kept output shape and verdict words. |
| `principles/` (4) | `prove-it-works`, `explain-the-number`, `attack-the-premise`, `encode-lessons-in-structure` | Shortened. Cross-skill links removed. |
| Three rules | `poteto-mode` router, `swarm`, `figure-it-out` | Three README lines instead of a 909-line router. Applied to `code-review` and `plan-review` as well. |
| `log.md` | purpose of `reflect` / `recall` | Manual one-liners instead of transcript mining. |
| `skills/correct` | skill `correct` (+ the transcript reading of `reflect`) — pstack c742dd6 | Inputs added: review-log, log.md; harness classes; a propose-then-approve step; proofs need a writable worktree, else BLOCKED. `reflect`'s three-lens fan-out not ported. |
| `commands/bro.md` | skill `bro` — pstack c742dd6 | A Claude Code command instead of a skill. pstack's one-line prompt plus rules from the user's corrections: no coined labels, whole sentences, one concrete case, plain over short. |
| `scripts/automerge.py`, `references/tiers.md` | playbook `autopilot-full` ("no owner merges on its own verdict", "only a clean verdict on the patch that merges authorizes the merge") — pstack c742dd6 | The author owns its PR until it merges or goes to the user (`/pr` step 9) but does not merge it: a script checks the facts and a fresh Claude that wrote and verified nothing makes the call, up to the medium tier. |
| `skills/code-review/verifier.md`, `scripts/verify_fresh.sh`, `scripts/record_review.py` | playbooks `shipping` (verifier lane), `autopilot-full` (live lane, "you own the verdicts, never the PRs") — pstack c742dd6 | One fresh headless session per commit instead of a cloud-agent swarm and a root agent. The verdict is enforced by a script and the push gate (`scripts/push_gate.py`) rather than by a root agent's audit. |

Not taken: the router body, the other 20 playbooks, the other 20 principles, ~7k lines of scripts, the automation pack, `disable-model-invocation`.

## License

MIT. Adapted pstack material remains under its original MIT license, Copyright (c) 2026 Lauren Tan.
