#!/usr/bin/env bash
# Start a fresh verifier session on a task worktree's current commit.
#
# The author does not review its own commit. This creates a new worktree at the same commit, starts a new
# headless Claude session there that has never seen the change being written (skills/code-review/verifier.md),
# and that session writes the review record itself through record_review.py. The author waits and reads the
# verdict. pstack: "Only a verdict from an agent that did not write the code counts."
#
# Usage: verify_fresh.sh <task worktree> [standard|full]
# Env:   KEEP=1 keeps the verifier worktree; VERIFIER_MODEL overrides the model.
set -euo pipefail

src="${1:?usage: verify_fresh.sh <task worktree> [standard|full]}"
mode="${2:-standard}"
case "$mode" in standard|full) ;; *) echo "mode must be standard or full" >&2; exit 64 ;; esac
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"     # hhmode root this script lives in

if [ -n "$(git -C "$src" status --porcelain --untracked-files=no)" ]; then
  echo "uncommitted changes in $src — the verifier checks a commit, so commit first" >&2; exit 65
fi
sha="$(git -C "$src" rev-parse HEAD)"
common="$(git -C "$src" rev-parse --git-common-dir)"
case "$common" in /*) ;; *) common="$(cd "$src" && cd "$common" && pwd)" ;; esac
main_repo="$(dirname "$common")"

vdir="$main_repo/.claude/worktrees/verify-${sha:0:7}"
if [ -e "$vdir" ]; then git -C "$main_repo" worktree remove --force "$vdir" 2>/dev/null || rm -rf "$vdir"; fi
git -C "$main_repo" worktree add -q --detach "$vdir" "$sha"
cleanup() {
  if [ "${KEEP:-0}" != "1" ]; then git -C "$main_repo" worktree remove --force "$vdir" 2>/dev/null || true; fi
}
trap cleanup EXIT

# Repo-specific setup: k-defense-kg assigns ports and links node_modules per worktree.
if [ -f "$vdir/scripts/agents/wt_env.sh" ]; then (cd "$vdir" && bash scripts/agents/wt_env.sh >/dev/null); fi

session="$(python3 -c 'import uuid; print(uuid.uuid4())')"
work="$vdir/.verify"
mkdir -p "$work"
record="python3 $here/scripts/record_review.py --repo $vdir --result $work/result.json --report $work/report.md --session $session"
prompt="Verify commit $sha. Your working directory $vdir is a fresh worktree at that commit; base is origin/main. \
Mode: $mode. Your session id: $session. Write result.json and report.md in $work, then run exactly: $record"

# Least privilege: the verifier reads, runs the repo's own checks, starts this worktree's servers, and writes its two
# output files plus the record (through record_review.py). It gets no general shell and no Edit.
tools=(
  # Edit(path) covers the Write tool too; a Write(path) rule is accepted but never matches (Claude Code docs,
  # "Write(path) ... rules never match"). Found when the first verifier run was BLOCKED unable to write.
  "Agent" "Read" "Grep" "Glob" "Edit(./.verify/**)"
  "Bash(git diff:*)" "Bash(git log:*)" "Bash(git show:*)" "Bash(git status:*)" "Bash(git rev-parse:*)"
  "Bash(python3 scripts/verify.py:*)" "Bash(python3 -m unittest:*)"
  "Bash(python3 $here/scripts/record_review.py:*)"
  "Bash(bash scripts/agents/wt_env.sh:*)" "Bash(bash scripts/agents/serve.sh:*)"
  "Bash(curl:*)" "Bash(ss -ltnp:*)" "Bash(kill:*)"
  "Bash($main_repo/.venv/bin/python .verify/:*)"
  # Read-only pip, for a dependency change's live lane: neither command installs anything.
  "Bash($main_repo/.venv/bin/python -m pip show:*)"
  "Bash($main_repo/.venv/bin/python -m pip install --dry-run:*)"
)

echo "verifier session $session on ${sha:0:7} ($mode) in $vdir"
(cd "$vdir" && claude -p "$prompt" \
    --session-id "$session" \
    --append-system-prompt-file "$here/skills/code-review/verifier.md" \
    --model "${VERIFIER_MODEL:-claude-opus-5-5}" \
    --allowedTools "${tools[@]}" \
    --output-format json) > "$work/session.json" 2> "$work/session.err" || true

rec="$common/gate/$sha.review.md"
if [ ! -f "$rec" ] || ! grep -q "verifier-session: $session" "$rec"; then
  echo "NO RECORD: the verifier did not write a review record for ${sha:0:7}." >&2
  python3 - "$work/session.json" <<'PY' >&2 || true
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    print("verifier said:", (d.get("result") or "")[:800])
except Exception as e:
    print("no verifier output:", e)
PY
  KEEP=1; echo "kept $vdir for inspection" >&2
  exit 1
fi
echo "record: $rec"
# The PR body's Review/Verify lines, taken from the records the verifier produced — the author pastes these
# instead of typing a verdict.
python3 - "$rec" "$common/gate/$sha.verify.json" <<'PY'
import json, sys
rec, vjson = sys.argv[1], sys.argv[2]
print("\n--- paste into the PR body (Verification) ---")
print(open(rec, encoding="utf-8").readline().strip())
try:
    v = json.load(open(vjson, encoding="utf-8"))
except OSError:
    print("**Verify: BLOCKED** · no verify record"); sys.exit(0)
print(f"**Verify: {v['verdict']}** · {v['sha'][:7]} · patch {v['patch'][:12]} · base main {v['base'][:7]}"
      f" · {v.get('changed', '?')} files changed · `python3 scripts/verify.py`\n")
print("| Check | Result | Time | Detail |\n|---|---|---|---|")
for c in v.get("checks", []) or [{"name": "(none selected)", "status": "-", "secs": 0, "detail": ""}]:
    print(f"| {c['name']} | {c['status']} | {round(c.get('secs') or 0)}s | {c.get('detail', '')} |")
PY
