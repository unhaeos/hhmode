#!/usr/bin/env bash
# Stage the Claude Code commands, skills and agents a commit changes, so the verifier can try them in a fresh session.
#
# Why: the verifier cannot write under .claude/ ("sensitive file") or start `claude` itself, so the live lane of every
# command/skill/agent change was BLOCKED (#6, #7, #8). The launcher runs this before the verifier starts.
#
# Each changed command, skill (any file under skills/<name>/) or agent is installed under <name>-new in
# <live dir>/.claude/: a project-level copy with the same name as an installed one in ~/.claude loses to it (probed
# 2026-10-29: a project /bro was ignored for the user's /bro).
# Writes <ask> (a helper the verifier may run) and prints the staged invocation names, one per line.
#
# Usage: stage_live_claude.sh <worktree> <live dir> <ask script path>
set -euo pipefail
wt=$1 live=$2 ask=$3
changed=$(git -C "$wt" diff --name-only origin/main...HEAD -- 'commands/*.md' 'skills/*' 'agents/*.md')
[ -n "$changed" ] || exit 0
mkdir -p "$live/.claude/commands" "$live/.claude/skills" "$live/.claude/agents"
staged=0
seen=" "
while IFS= read -r f; do
  case "$f" in
    commands/*)
      [ -f "$wt/$f" ] || continue                           # deleted in this commit
      n=$(basename "$f" .md)
      cp "$wt/$f" "$live/.claude/commands/$n-new.md"
      echo "/$n-new" ;;
    skills/*)
      n=$(printf '%s' "$f" | cut -d/ -f2)
      case "$seen" in *" $n "*) continue ;; esac
      seen="$seen$n "
      [ -f "$wt/skills/$n/SKILL.md" ] || continue           # skill deleted in this commit
      rm -rf "$live/.claude/skills/$n-new"
      cp -r "$wt/skills/$n" "$live/.claude/skills/$n-new"
      sed -i "0,/^name: .*/s//name: $n-new/" "$live/.claude/skills/$n-new/SKILL.md"
      echo "skill $n-new" ;;
    agents/*)
      [ -f "$wt/$f" ] || continue
      n=$(basename "$f" .md)
      sed "0,/^name: .*/s//name: $n-new/" "$wt/$f" > "$live/.claude/agents/$n-new.md"
      echo "agent $n-new" ;;
    *) continue ;;
  esac
  staged=$((staged + 1))
done <<< "$changed"
[ "$staged" -gt 0 ] || { rm -rf "$live"; exit 0; }

cat > "$ask" <<EOF
#!/usr/bin/env bash
# Ask a fresh Claude session in $live, where this commit's changed commands, skills and agents are installed as
# <name>-new. Prints the JSON reply (session_id, result).
#   bash .verify/ask.sh "<prompt>"
#   bash .verify/ask.sh --resume <session_id> "<prompt>"
# The session loads no user settings (no allowlist, no default mode) and has read-only tools, so a staged command
# cannot write anything real; with no user settings even read-only Bash is refused, so Bash is not offered (probed
# 2026-10-29). The prompt goes on stdin because --tools takes several values and would swallow a positional prompt.
cd "$live" || exit 1
iso=(--output-format json --setting-sources project --tools "Read,Grep,Glob")
if [ "\${1:-}" = --resume ]; then printf '%s' "\$3" | claude -p --resume "\$2" "\${iso[@]}"; exit \$?; fi
printf '%s' "\$1" | claude -p "\${iso[@]}"
EOF
