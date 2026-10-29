#!/usr/bin/env bash
# Bring this hhmode checkout up to origin/main and link any new skill or agent into ~/.claude.
# Runs as a Claude Code SessionStart hook: at session start, not from cron (the user prefers events to polling).
#
# Why: ~/.claude reads skills, agents and commands from this checkout through symlinks. After a PR was merged
# on GitHub the checkout stayed on the old commit and a new skill had no link: on 2026-10-29 /correct (#5) and
# /bro (#6) were merged but unusable until someone pulled and linked them by hand.
#
# Same safety rules as k-defense-kg scripts/agents/sync_main.sh:
#   - updates only when the checkout is on main with no tracked changes; fast-forward only
#   - never overwrites an ignored local file (--no-overwrite-ignore; local/ is gitignored)
#   - links only names that do not exist in ~/.claude/skills or ~/.claude/agents; never replaces anything
#   - fetch has a timeout; one run at a time; always exits 0, so a session always starts
# Prints one line only when it changed something; SessionStart output goes into the session's context.
#
# HHMODE_DIR and CLAUDE_DIR override the paths (tests point them at scratch dirs).
set -uo pipefail
HH=${HHMODE_DIR:-$HOME/projects/hhmode}
CL=${CLAUDE_DIR:-$HOME/.claude}

exec 9>"${TMPDIR:-/tmp}/hhmode-sync-$(id -u).lock"
flock -n 9 || exit 0
cd "$HH" 2>/dev/null || exit 0

msg=()
branch=$(git symbolic-ref --short -q HEAD)
if [ "$branch" = main ] && [ -z "$(GIT_OPTIONAL_LOCKS=0 git status --porcelain --untracked-files=no)" ] \
   && timeout 5 git fetch -q origin main 9>&- 2>/dev/null; then
  before=$(git rev-parse HEAD)
  target=$(git rev-parse origin/main)
  if [ "$before" != "$target" ] && git merge-base --is-ancestor "$before" "$target"; then
    if git merge -q --ff-only --no-overwrite-ignore "$target" 9>&- >/dev/null 2>&1; then
      msg+=("updated ${before:0:7} -> ${target:0:7}")
    else
      msg+=("update to ${target:0:7} refused by git (an ignored local file would be overwritten?); left as is")
    fi
  fi
fi

# commands/ is linked as one directory and needs nothing here.
linked=()
for s in "$HH"/skills/*/; do
  [ -f "${s}SKILL.md" ] || continue
  n=$(basename "$s")
  [ -e "$CL/skills/$n" ] || [ -L "$CL/skills/$n" ] || { ln -s "${s%/}" "$CL/skills/$n" && linked+=("skill:$n"); }
done
for a in "$HH"/agents/*.md; do
  [ -f "$a" ] || continue
  n=$(basename "$a")
  [ -e "$CL/agents/$n" ] || [ -L "$CL/agents/$n" ] || { ln -s "$a" "$CL/agents/$n" && linked+=("agent:${n%.md}"); }
done
[ ${#linked[@]} -gt 0 ] && msg+=("linked ${linked[*]}")
[ ${#msg[@]} -gt 0 ] && echo "[hhmode sync] ${msg[*]}"
exit 0
