#!/usr/bin/env bash
# Start a fresh verifier session on a task worktree's current commit.
#
# The author does not review its own commit. This creates a new worktree at the same commit, starts a new
# headless Claude session there that has never seen the change being written (skills/code-review/verifier.md),
# and that session writes the review record itself through record_review.py. The author waits and reads the
# verdict. pstack: "Only a verdict from an agent that did not write the code counts."
#
# Usage: verify_fresh.sh <task worktree> [standard|full]
# Env:   KEEP=1 keeps the verifier worktree; VERIFIER_MODEL overrides the model; WHOLE=1 reviews the whole branch
#        diff even when an earlier commit on it was already reviewed; PRINT_PROMPT=1 prints the verifier's prompt
#        and exits without starting it.
#
# Proportional (pstack autopilot-full): when an earlier commit on this branch has a PASS or ISSUES verifier record
# in at least this mode, the review lanes read only the diff after it (`--since`). When this commit already has a verify record that ran (PASS or
# FAIL), the verifier reads it instead of running verify.py again — about ten minutes in k-defense-kg, where the
# verifier re-ran the author's verify on the same sha (verify-d89c2a1, 2026-10-29). A BLOCKED record runs again.
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

# k-defense-kg expects task worktrees under .claude/worktrees (wt_env.sh assigns ports there). Any other repo gets
# the verifier worktree outside itself, so a run never leaves files in a repo that is live (hhmode is symlinked
# into ~/.claude).
if [ -f "$main_repo/scripts/agents/wt_env.sh" ]; then
  vdir="$main_repo/.claude/worktrees/verify-${sha:0:7}"
else
  vdir="${TMPDIR:-/tmp}/verify-$(basename "$main_repo")-${sha:0:7}"
fi
if [ -e "$vdir" ]; then git -C "$main_repo" worktree remove --force "$vdir" 2>/dev/null || rm -rf "$vdir"; fi
git -C "$main_repo" worktree add -q --detach "$vdir" "$sha"
cleanup() {
  if [ "${KEEP:-0}" != "1" ]; then
    git -C "$main_repo" worktree remove --force "$vdir" 2>/dev/null || true
    rm -rf "$vdir.live"
  fi
}
trap cleanup EXIT

# Repo-specific setup: k-defense-kg assigns ports and links node_modules per worktree.
if [ -f "$vdir/scripts/agents/wt_env.sh" ]; then (cd "$vdir" && bash scripts/agents/wt_env.sh >/dev/null); fi

session="$(python3 -c 'import uuid; print(uuid.uuid4())')"
work="$vdir/.verify"
mkdir -p "$work"

# The newest earlier commit on this branch that a verifier reviewed with every lane run (PASS or ISSUES) in at
# least this mode — the same test record_review.py --since applies.
since=""
if [ "${WHOLE:-0}" != "1" ]; then
  since=$(python3 - "$here/scripts" "$common/gate" "$mode" "$sha" $(git -C "$src" rev-list origin/main..HEAD 2>/dev/null) <<'PY'
import pathlib, sys
sys.path.insert(0, sys.argv[1])
import record_review as rr
gate, mode, head = pathlib.Path(sys.argv[2]), sys.argv[3], sys.argv[4]
for c in sys.argv[5:]:
    p = gate / f"{c}.review.md"
    got = rr.reviewed_as(p.read_text(encoding="utf-8")) if c != head and p.exists() else None
    if got and rr.STRENGTH[got] >= rr.STRENGTH[mode]:
        print(c)
        break
PY
)
fi
# This commit's verify record, if verify.py already ran to a verdict (not BLOCKED).
vrec="$common/gate/$sha.verify.json"
vdone=$(python3 - "$vrec" "$sha" <<'PY' 2>/dev/null || true
import json, sys
try:
    v = json.load(open(sys.argv[1], encoding="utf-8"))
except OSError:
    sys.exit(0)
if str(v.get("sha", "")) == sys.argv[2] and str(v.get("verdict", "")).upper() in ("PASS", "FAIL"):
    print(str(v["verdict"]).upper())
PY
)

record="python3 $here/scripts/record_review.py --repo $vdir --result $work/result.json --report $work/report.md --session $session --mode $mode${since:+ --since $since}"
py=python3; [ -x "$main_repo/.venv/bin/python" ] && py="$main_repo/.venv/bin/python"
# Commands, skills and agents this commit changes, staged as <name>-new outside the worktree for the live lane.
staged=$(bash "$here/scripts/stage_live_claude.sh" "$vdir" "$vdir.live" "$work/ask.sh" 2>"$work/stage.err") || staged=""
prompt="Verify commit $sha. Your working directory $vdir is a fresh worktree at that commit; base is origin/main. \
Mode: $mode. Your session id: $session. Python for .verify/ scripts and tests: $py. \
Write result.json and report.md in $work, then run exactly: $record"
if [ -n "$since" ]; then
  prompt="$prompt
Scope: ${since:0:7} was already reviewed (record $common/gate/$since.review.md). Review lanes read only \
git diff $since..HEAD, plus that record to check its findings were addressed (verifier.md step 3)."
fi
if [ -n "$vdone" ]; then
  prompt="$prompt
Verify: $vrec already holds verdict $vdone for this commit, written by scripts/verify.py. Read it; do not run \
verify.py again (verifier.md step 2)."
fi
if [ -n "$staged" ]; then
  prompt="$prompt
This commit changes Claude Code files, staged for the live lane as: $(printf '%s' "$staged" | paste -sd ',' -). \
Try them with bash .verify/ask.sh (verifier.md step 4)."
fi

# Least privilege: the verifier reads, runs the repo's own checks, starts this worktree's servers, and writes its two
# output files plus the record (through record_review.py). It gets no general shell and no Edit.
tools=(
  # Edit(path) covers the Write tool too; a Write(path) rule is accepted but never matches (Claude Code docs,
  # "Write(path) ... rules never match"). Found when the first verifier run was BLOCKED unable to write.
  "Agent" "Read" "Grep" "Glob" "Edit(./.verify/**)"
  # git ls-tree: the rules lane lists rule files on origin/main; denied in 4 of 12 verifier sessions (2026-10-29).
  "Bash(git diff:*)" "Bash(git log:*)" "Bash(git show:*)" "Bash(git status:*)" "Bash(git rev-parse:*)"
  "Bash(git ls-tree:*)"
  "Bash(python3 scripts/verify.py:*)" "Bash(python3 -m unittest:*)"
  "Bash($main_repo/.venv/bin/python -m unittest:*)"
  "Bash(python3 $here/scripts/record_review.py:*)"
  "Bash(bash scripts/agents/wt_env.sh:*)" "Bash(bash scripts/agents/serve.sh:*)"
  "Bash(curl:*)" "Bash(ss -ltnp:*)" "Bash(kill:*)"
  # Live-lane scripts the verifier writes under .verify/. Glob form: a `.verify/:*` prefix rule only matches when a
  # space follows the prefix, so `python .verify/live.py` was refused every time (probed with claude -p
  # 2.1.312, 2026-10-29; k-defense-kg verify-3c24b2f was refused .venv/bin/python .verify/live_hwpx.py).
  "Bash($main_repo/.venv/bin/python .verify/*)" "Bash(python3 .verify/*)"
  # Read-only pip, for a dependency change's live lane: neither command installs anything.
  "Bash($main_repo/.venv/bin/python -m pip show:*)"
  "Bash($main_repo/.venv/bin/python -m pip install --dry-run:*)"
)
# The helper that runs a fresh `claude -p` in the staged folder, only when something was staged.
[ -n "$staged" ] && tools+=("Bash(bash .verify/ask.sh:*)")

# VERIFIER_READ_DIRS: extra directories the verifier may read (space-separated), for a change whose live lane
# must read real inputs outside the worktree — e.g. a skill that reads ~/.claude/review-log. Read access only:
# the Edit rule above still limits writes to ./.verify.
add_dirs=()
for d in ${VERIFIER_READ_DIRS:-}; do add_dirs+=(--add-dir "$d"); done

echo "verifier session $session on ${sha:0:7} ($mode${since:+, since ${since:0:7}}${vdone:+, verify record reused}) in $vdir"
if [ "${PRINT_PROMPT:-0}" = "1" ]; then printf '%s\n' "$prompt"; exit 0; fi     # dry run: what the verifier would get
(cd "$vdir" && claude -p "$prompt" \
    ${add_dirs[@]+"${add_dirs[@]}"} \
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
# The verifier builds the record command itself, so check the mode it recorded is the one asked for.
if ! head -n 1 "$rec" | grep -qF "· $mode ·"; then
  echo "MODE MISMATCH: asked for $mode, record says: $(head -n 1 "$rec")" >&2
  KEEP=1; echo "kept $vdir for inspection" >&2
  exit 1
fi
echo "record: $rec"
# The PR body's Review/Verify lines, taken from the records the verifier produced — the author pastes these
# instead of typing a verdict.
python3 - "$rec" "$common/gate/$sha.verify.json" <<'PY'
import json, re, sys
rec, vjson = sys.argv[1], sys.argv[2]
text = open(rec, encoding="utf-8").read()
print("\n--- paste into the PR body (Verification) ---")
print(text.splitlines()[0].strip())
try:
    v = json.load(open(vjson, encoding="utf-8"))
except OSError:
    # No verify.json: the repo has no verify step and the verifier's own test lane decided (record_review.py
    # wrote that verdict into the record's provenance comment).
    m = re.search(r"verify: (PASS|FAIL|BLOCKED);", text)
    sha7 = text.split("·")[1].strip() if "·" in text else "?"
    print(f"**Verify: {m.group(1) if m else 'BLOCKED'}** · {sha7} · verifier's test lane (no scripts/verify.py)"
          " — command and output in the record")
    sys.exit(0)
print(f"**Verify: {v['verdict']}** · {v['sha'][:7]} · patch {v['patch'][:12]} · base main {v['base'][:7]}"
      f" · {v.get('changed', '?')} files changed · `python3 scripts/verify.py`\n")
print("| Check | Result | Time | Detail |\n|---|---|---|---|")
for c in v.get("checks", []) or [{"name": "(none selected)", "status": "-", "secs": 0, "detail": ""}]:
    print(f"| {c['name']} | {c['status']} | {round(c.get('secs') or 0)}s | {c.get('detail', '')} |")
PY
