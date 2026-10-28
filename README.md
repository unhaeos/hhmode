# hhmode

A small, git-tracked agent harness shared by Claude Code and Codex. Everything here is plain text; each tool reads it through a symlink into the directory it already scans. Nothing runs on its own.

Modeled on [pstack](https://github.com/poteto/pstack) by Lauren Tan, deliberately kept to the parts that have earned their place. A rule gets added here only after the same failure has shown up twice.

## Layout

```
skills/        One SKILL.md per skill. Symlinked into ~/.claude/skills/<name> and ~/.codex/skills/<name>.
agents/        Subagent definitions (reviewers). Symlinked into ~/.claude/agents/<name>.md.
commands/      Claude Code slash commands (Claude Code only). ~/.claude/commands -> this folder.
principles/    One principle per file. Skills reference them by absolute path.
log.md         Failure log, one line per incident.
local/         Machine-local values (identity, paths). Gitignored.
```

Not here yet, added when a need appears: a router, per-repo `features/` maps, verification scripts.

## Install (new machine)

```
git clone git@github.com:haehoonseo/hhmode.git ~/projects/hhmode
for s in ~/projects/hhmode/skills/*/; do ln -sfn "$s" ~/.claude/skills/$(basename "$s"); done
for s in hillclimb investigate; do ln -sfn ~/projects/hhmode/skills/$s ~/.codex/skills/$s; done
ln -sfn ~/projects/hhmode/commands ~/.claude/commands
for a in ~/projects/hhmode/agents/*.md; do ln -sfn "$a" ~/.claude/agents/$(basename "$a"); done
```

Machine-local values go in `local/` (gitignored); see `commands/*.md` for what they read.

## Usage

Nothing to start. The symlinks make every skill available in any directory where Claude Code or Codex runs.

| Situation | Type |
|---|---|
| Improve one metric toward a target | `/hillclimb <metric> to <target>` |
| Find out why something happens, read-only | `/investigate <question>`, or just ask "why does X ..." |
| Review staged changes before a commit | `git add ...` then `/code-review` |
| Open a PR from a task worktree, with evidence | `/pr` |
| Merge one reviewed PR (merge-owner session) | `/land <PR#>` |
| Stress-test a plan before implementing | `/plan-review <path to plan>` |
| Write up results as a document | ask for a report; the `report` skill loads on its own |
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
| `report` | yes (uses the Artifact tool) | no |
| `commands/*` | yes | no |

## Skills

| Skill | Purpose |
|---|---|
| `hillclimb` | Iterative improvement of one metric: fixed stop predicate, frozen measurement harness, one hypothesis per iteration, keep or revert, `decision.tsv`. |
| `investigate` | Read-only investigation ending in a cited explanation or recommendation. |
| `code-review` | Opus bug reviewer (repo access, may run tests) + Sonnet rules reviewer; every P0/P1 re-checked by an Opus validator that tries to reproduce it; runs on every PR via `/pr`; full mode adds diff-only and Fable reviewers. |
| `plan-review` | One repo-reading reviewer checks the plan's assumptions, order, verification and irreversible steps against the code; open questions come back as experiments. No design debate (pstack: review the diff, not the plan). |
| `report` | House style for written reports as HTML artifacts. |

## Taken from pstack

Source: pstack v0.15.32, MIT. Each adapted file notes its origin at the bottom.

| Here | pstack original | Changed |
|---|---|---|
| `skills/hillclimb` | playbook `hillclimb` | Removed Cursor subagent/model routing, worktree fan-out, PR steps. Added a prior-work check as step 1. |
| `skills/investigate` | playbook `investigation`, skill `figure-it-out` | Removed how/why/unslop routing. Kept output shape and verdict words. |
| `principles/` (4) | `prove-it-works`, `explain-the-number`, `attack-the-premise`, `encode-lessons-in-structure` | Shortened. Cross-skill links removed. |
| Three rules | `poteto-mode` router, `swarm`, `figure-it-out` | Three README lines instead of a 909-line router. Applied to `code-review` and `plan-review` as well. |
| `log.md` | purpose of `reflect` / `recall` | Manual one-liners instead of transcript mining. |

Not taken: the router body, the other 21 playbooks, the other 20 principles, ~7k lines of scripts, the automation pack, `disable-model-invocation`.

## License

MIT. Adapted pstack material remains under its original MIT license, Copyright (c) 2026 Lauren Tan.
