#!/usr/bin/env bash
# Start a fresh verifier session on a task worktree's current commit.
#
# The author does not review its own commit. This creates a new worktree at the same commit, starts a new
# headless Claude session there that has never seen the change being written (skills/code-review/verifier.md),
# and that session writes the review record itself through record_review.py. The author waits and reads the
# verdict. pstack: "Only a verdict from an agent that did not write the code counts."
#
# Usage: verify_fresh.sh <task worktree> [standard]
# Env:   KEEP=1 keeps the verifier worktree; VERIFIER_MODEL overrides the model; WHOLE=1 reviews the whole branch
#        diff even when an earlier commit on it was already reviewed; PRINT_PROMPT=1 prints the verifier's prompt
#        and exits without starting it; VERIFIER_TIMEOUT is the most seconds the verifier may run (default 3600).
#
# Proportional (pstack autopilot-full: "a rebase, a merge-conflict resolution, or a minor fix gets a single verifier
# at the new head, and a wording-only change gets none"): scripts/review_weight.py decides from what changed since the
# newest earlier commit on this branch that a verifier reviewed (PASS or ISSUES):
#   carry     only wording changed since a PASS: no session starts, the earlier record is carried over
#   fix       a small change that adds no file: one verifier, lanes bug, verify and live, on `git diff since..HEAD`
#   standard  the first review, a large change or a new file: every lane, Codex alongside
# The mode argument is advice: `standard` forces a standard review, and `full` (the old name) means the same. Without
# it the weight decides.
#
# When this commit already has a verify record that ran (PASS or FAIL), the verifier reads it instead of running
# verify.py again — about ten minutes in k-defense-kg, where the verifier re-ran the author's verify on the same sha
# (verify-d89c2a1, 2026-10-29). A BLOCKED record runs again.
#
# Issues (scripts/forms.py): a commit message that says `Closes #<n>` names the issue this branch answers. Its text is
# written to .verify/issues.md; the verifier judges every acceptance criterion in it, and Codex reads it too. An issue
# that cannot be read stops the run (NO ISSUE, exit 1) rather than being skipped, so a criterion is never dropped by
# accident.
#
# The verifier is not waited on once it is done: headless sessions stayed open 6 and 12 minutes after writing their
# records, holding HTTPS connections with no child process, and earlier ones idled 16 and 52 minutes (measured
# 2026-10-30). So this waits for the record, gives the session 30 s to exit, and stops it.
set -euo pipefail

src="${1:?usage: verify_fresh.sh <task worktree> [standard]}"
asked="${2:-}"
case "$asked" in
  ""|standard) ;;
  full) asked=standard ;;                  # the old name: a full review is a standard one now
  *) echo "the only review you can ask for is standard (leave it out and the change decides)" >&2; exit 64 ;;
esac
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"     # hhmode root this script lives in

if [ -n "$(git -C "$src" status --porcelain --untracked-files=no)" ]; then
  echo "uncommitted changes in $src — the verifier checks a commit, so commit first" >&2; exit 65
fi
sha="$(git -C "$src" rev-parse HEAD)"
common="$(git -C "$src" rev-parse --git-common-dir)"
case "$common" in /*) ;; *) common="$(cd "$src" && cd "$common" && pwd)" ;; esac
main_repo="$(dirname "$common")"
gate="$common/gate"

# The newest earlier commit on this branch whose verifier record counts as a review (PASS or ISSUES) in at least mode $1
# (fix or standard) — the same test record_review.py --since applies.
newest_review() {
  python3 - "$here/scripts" "$gate" "$1" "$sha" $(git -C "$src" rev-list origin/main..HEAD 2>/dev/null) <<'PY'
import pathlib, sys
sys.path.insert(0, sys.argv[1])
import record_review as rr
gate, weakest, head = pathlib.Path(sys.argv[2]), sys.argv[3], sys.argv[4]
for c in sys.argv[5:]:
    p = gate / f"{c}.review.md"
    got = rr.reviewed_as(p.read_text(encoding="utf-8")) if c != head and p.exists() else None
    if got and rr.STRENGTH[got] >= rr.STRENGTH[weakest]:
        print(c)
        break
PY
}

# The PR body's Review/Verify lines ($1: the review record, $2: the verify record), taken from the records the
# verifier produced — the author pastes these instead of typing a verdict.
paste_lines() {
  python3 - "$1" "$2" <<'PY'
import json, re, sys
rec, vjson = sys.argv[1], sys.argv[2]
text = open(rec, encoding="utf-8").read()
first = text.splitlines()[0].strip()
print("\n--- paste into the PR body (Verification) ---")
print(first)
try:
    v = json.load(open(vjson, encoding="utf-8"))
except OSError:
    # No verify.json: either a carried record (no verifier ran on this commit), or the repo has no verify step and the
    # verifier's own test lane decided (record_review.py wrote that verdict into the record's provenance comment).
    m = re.search(r"verify: (PASS|FAIL|BLOCKED);", text)
    verdict = m.group(1) if m else "BLOCKED"
    sha7 = text.split("·")[1].strip() if "·" in text else "?"
    if " · carry · since " in first:
        print(f"**Verify: {verdict}** · {sha7} · carried from {first.split(' · since ')[1].split(' ')[0]}, where the"
              " tests passed; only wording changed since")
    else:
        print(f"**Verify: {verdict}** · {sha7} · verifier's test lane (no scripts/verify.py)"
              " — command and output in the record")
    sys.exit(0)
print(f"**Verify: {v['verdict']}** · {v['sha'][:7]} · patch {v['patch'][:12]} · base main {v['base'][:7]}"
      f" · {v.get('changed', '?')} files changed · `python3 scripts/verify.py`\n")
print("| Check | Result | Time | Detail |\n|---|---|---|---|")
for c in v.get("checks", []) or [{"name": "(none selected)", "status": "-", "secs": 0, "detail": ""}]:
    print(f"| {c['name']} | {c['status']} | {round(c.get('secs') or 0)}s | {c.get('detail', '')} |")
PY
}

# How much review: the newest reviewed commit on the branch is the base, and review_weight.py weighs what changed since.
since=""
if [ "${WHOLE:-0}" != "1" ]; then since=$(newest_review fix); fi
weight=$(python3 "$here/scripts/review_weight.py" "$src" "$since" "$sha")
kind="${weight%%$'\t'*}"; reason="${weight#*$'\t'}"
if [ "${WHOLE:-0}" = "1" ]; then
  kind=standard; reason="WHOLE=1 reviews the whole branch."
elif [ -n "$asked" ] && [ "$kind" != standard ]; then
  kind=standard; reason="A standard review was asked for."
fi
# A standard review may only start after a review at least as strong as standard; a fix record is weaker.
if [ "$kind" = standard ] && [ -n "$since" ]; then since=$(newest_review standard); fi
echo "review: $kind. $reason"

# Wording only: nothing to run, so no worktree, no Codex, no Claude.
if [ "$kind" = carry ]; then
  if [ "${PRINT_PROMPT:-0}" = "1" ]; then echo "(dry run: no record written)"; exit 0; fi
  if python3 "$here/scripts/record_review.py" --repo "$src" --carry "$since"; then
    echo "record: $gate/$sha.review.md"
    paste_lines "$gate/$sha.review.md" "$gate/$sha.verify.json"
    exit 0
  fi
  # A carry the record script refuses (this commit has no verify record of its own in a repo with a verify step, a
  # failed one, or a verifier's record already) gets one verifier instead of stopping (verifier on 79691db).
  kind=fix; reason="The earlier result could not be carried (see above), so one verifier checks this commit."
  echo "review: $kind. $reason"
fi

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

stop_tree() {           # $1: a pid. Stops it and everything it started: TERM, then KILL for what is left after 5 s.
  local pids=("$1") i=0 n
  while [ "$i" -lt "${#pids[@]}" ]; do
    pids+=($(pgrep -P "${pids[$i]}" 2>/dev/null || true))
    i=$((i + 1))
  done
  kill "${pids[@]}" 2>/dev/null || true
  for n in 1 2 3 4 5; do
    if ! kill -0 "${pids[@]}" 2>/dev/null; then return 0; fi
    sleep 1
  done
  kill -KILL "${pids[@]}" 2>/dev/null || true
}
cleanup() {
  # Whatever is still running (a verifier past its limit, Codex when the run stopped early) must not outlive the worktree.
  if [ -n "${vpid:-}" ] && kill -0 "$vpid" 2>/dev/null; then stop_tree "$vpid"; fi
  if [ -n "${codex_pid:-}" ] && kill -0 "$codex_pid" 2>/dev/null; then stop_tree "$codex_pid"; fi
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

# The issues this branch closes, from its commit messages. PRINT_PROMPT=1 stays offline: it lists the numbers only.
issues="$work/issues.md"
: > "$issues"
issue_nums=$(git -C "$src" log --format=%B origin/main..HEAD 2>/dev/null | python3 -c '
import sys
sys.path.insert(0, sys.argv[1])
import forms
print(*forms.closes(sys.stdin.read()))' "$here/scripts" || true)
for n in $issue_nums; do
  if [ "${PRINT_PROMPT:-0}" = "1" ]; then
    printf '# Issue #%s: (not read: dry run)\n\n' "$n" >> "$issues"
  elif one=$(cd "$src" && gh issue view "$n" --json number,title,body \
               --jq '"# Issue #\(.number): \(.title)\n\n\(.body // "")\n"' 2>"$work/issue.err"); then
    printf '%s\n' "$one" >> "$issues"
  else
    echo "NO ISSUE: could not read issue #$n: $(cat "$work/issue.err")" >&2
    exit 1
  fi
done

# This commit's verify record, if verify.py already ran to a verdict (not BLOCKED).
vrec="$gate/$sha.verify.json"
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

# GPT lane, standard reviews only: a reviewer from another company, since a same-family reviewer shares the author's
# blind spots (pstack pairs Opus with Grok in its reviewer panels). It runs in the background, started before the
# verifier so the two work at once; the verifier waits for it with .verify/wait_codex.sh before it records, and
# validates its P0/P1 like any other lane's. It reads the same scope as the other review lanes. Codex answers in JSON
# (skills/code-review/gpt-review.schema.json); codex_review.py renders that as the markdown the verifier and
# automerge read. Not started on a dry run, which must not call out.
gpt="$work/gpt-review.md"
gpt_status="$work/gpt-status"
set_gpt_status() { printf '%s\n' "$1" > "$gpt_status.tmp" && mv "$gpt_status.tmp" "$gpt_status"; }
run_codex() {
  local gbase gpt_issues=()
  [ -s "$issues" ] && gpt_issues=("$issues")
  gbase="${since:-$(git -C "$vdir" merge-base origin/main HEAD 2>/dev/null || true)}"
  if ! command -v codex >/dev/null; then
    set_gpt_status "blocked: codex CLI not installed"
  elif [ -z "$gbase" ]; then
    set_gpt_status "blocked: no origin/main to diff against"
  elif ! python3 "$here/scripts/gpt_review_input.py" "$vdir" "$gbase" ${gpt_issues[@]+"${gpt_issues[@]}"} \
         > "$work/gpt-input.md" 2> "$work/gpt-input.err"; then
    set_gpt_status "blocked: building the input failed, see $work/gpt-input.err"
  elif timeout 1500 codex exec -s read-only --ephemeral -C "$vdir" -c 'model_reasoning_effort="high"' \
         --output-schema "$here/skills/code-review/gpt-review.schema.json" -o "$work/gpt-review.json" \
         "$(cat "$here/skills/code-review/gpt-reviewer.md" "$here/skills/code-review/references/tiers.md")" \
         < "$work/gpt-input.md" > "$work/gpt-review.log" 2>&1 \
       && python3 "$here/scripts/codex_review.py" "$work/gpt-review.json" > "$gpt" 2>> "$work/gpt-review.log" \
       && [ -s "$gpt" ]; then
    set_gpt_status ran
  else
    set_gpt_status "blocked: codex exec failed, see $work/gpt-review.log"
  fi
}
codex_pid=""
if [ "$kind" = standard ] && [ "${PRINT_PROMPT:-0}" != "1" ]; then
  set_gpt_status running
  # What the verifier runs (it may not start Codex or sleep in a loop itself) to learn Codex is done.
  cat > "$work/wait_codex.sh" <<'SH'
#!/usr/bin/env bash
# Waits until Codex is done (the status file beside this script no longer says "running"), at most 25 minutes, and prints it.
f="$(dirname "$0")/gpt-status"
for ((i = 0; i < 1500; i++)); do
  if [ "$(cat "$f")" != running ]; then break; fi
  sleep 1
done
s="$(cat "$f")"
if [ "$s" = running ]; then s="blocked: Codex had not finished after 25 minutes"; fi
echo "$s"
SH
  run_codex &
  codex_pid=$!
fi

record="python3 $here/scripts/record_review.py --repo $vdir --result $work/result.json --report $work/report.md --session $session --mode $kind${since:+ --since $since}"
[ -s "$issues" ] && record="$record --issues $issues"
py=python3; [ -x "$main_repo/.venv/bin/python" ] && py="$main_repo/.venv/bin/python"
# Commands, skills and agents this commit changes, staged as <name>-new outside the worktree for the live lane.
staged=$(bash "$here/scripts/stage_live_claude.sh" "$vdir" "$vdir.live" "$work/ask.sh" 2>"$work/stage.err") || staged=""
prompt="Verify commit $sha. Your working directory $vdir is a fresh worktree at that commit; base is origin/main. \
Mode: $kind. Your session id: $session. Python for .verify/ scripts and tests: $py. \
Write result.json and report.md in $work, then run exactly: $record"
if [ "$kind" = fix ]; then
  prompt="$prompt
This is a fix round: the lanes are bug, verify and live, with no rules lane and no GPT lane (Codex does not run). \
${since:0:7} was already reviewed (record $gate/$since.review.md). The bug lane reads only git diff $since..HEAD, \
plus that record to check its findings were addressed (verifier.md step 3)."
else
  prompt="$prompt
GPT lane (bug-gpt): Codex is reviewing the same scope in the background, started before you. Before you read its \
review or record this lane, run exactly: bash .verify/wait_codex.sh. It waits until Codex is done and prints ran or \
blocked: <reason>. Its review is $gpt (verifier.md step 3)."
  if [ -n "$since" ]; then
    prompt="$prompt
Scope: ${since:0:7} was already reviewed (record $gate/$since.review.md). Review lanes read only \
git diff $since..HEAD, plus that record to check its findings were addressed (verifier.md step 3)."
  fi
fi
if [ -s "$issues" ]; then
  inums=$(printf '#%s, ' $issue_nums)
  prompt="$prompt
Issues: this branch closes ${inums%, }; their text is in $issues. Judge every acceptance criterion in it and give \
each one an entry in the criteria list of result.json (verifier.md step 5)."
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
# The helper that waits for Codex, only in a review where Codex runs. No `:*`: it takes no arguments.
[ "$kind" = standard ] && tools+=("Bash(bash .verify/wait_codex.sh)")

# VERIFIER_READ_DIRS: extra directories the verifier may read (space-separated), for a change whose live lane
# must read real inputs outside the worktree — e.g. a skill that reads ~/.claude/review-log. Read access only:
# the Edit rule above still limits writes to ./.verify.
add_dirs=()
for d in ${VERIFIER_READ_DIRS:-}; do add_dirs+=(--add-dir "$d"); done

echo "verifier session $session on ${sha:0:7} ($kind${since:+, since ${since:0:7}}${vdone:+, verify record reused}) in $vdir"
if [ "${PRINT_PROMPT:-0}" = "1" ]; then printf '%s\n' "$prompt"; exit 0; fi     # dry run: what the verifier would get

# Started in the background and watched, not waited on: the session can stay open long after it wrote the record.
rec="$gate/$sha.review.md"
(cd "$vdir" && exec claude -p "$prompt" \
    ${add_dirs[@]+"${add_dirs[@]}"} \
    --session-id "$session" \
    --append-system-prompt-file "$here/skills/code-review/verifier.md" \
    --model "${VERIFIER_MODEL:-claude-opus-5-5}" \
    --allowedTools "${tools[@]}" \
    --output-format json) < /dev/null > "$work/session.json" 2> "$work/session.err" &
vpid=$!
started=$SECONDS recorded="" timed_out=0
while kill -0 "$vpid" 2>/dev/null; do
  if [ -z "$recorded" ] && [ -f "$rec" ] && grep -q "verifier-session: $session" "$rec"; then recorded=$SECONDS; fi
  if [ -n "$recorded" ] && [ $((SECONDS - recorded)) -ge 30 ]; then break; fi
  if [ $((SECONDS - started)) -ge "${VERIFIER_TIMEOUT:-3600}" ]; then timed_out=1; break; fi
  sleep 1
done
if kill -0 "$vpid" 2>/dev/null; then
  if [ -n "$recorded" ]; then echo "the verifier wrote its record and stayed open for 30 s; stopped it"; fi
  stop_tree "$vpid"
fi
wait "$vpid" 2>/dev/null || true

if [ ! -f "$rec" ] || ! grep -q "verifier-session: $session" "$rec"; then
  if [ "$timed_out" = 1 ]; then
    echo "TIMEOUT: the verifier was still working after ${VERIFIER_TIMEOUT:-3600} s and had not written a review record for ${sha:0:7}; stopped it." >&2
  else
    echo "NO RECORD: the verifier did not write a review record for ${sha:0:7}." >&2
    python3 - "$work/session.json" <<'PY' >&2 || true
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    print("verifier said:", (d.get("result") or "")[:800])
except Exception as e:
    print("no verifier output:", e)
PY
  fi
  KEEP=1; echo "kept $vdir for inspection" >&2
  exit 1
fi
# The verifier builds the record command itself, so check the mode it recorded is the one asked for.
if ! head -n 1 "$rec" | grep -qF "· $kind ·"; then
  echo "MODE MISMATCH: asked for $kind, record says: $(head -n 1 "$rec")" >&2
  KEEP=1; echo "kept $vdir for inspection" >&2
  exit 1
fi
# A PR that closes an issue is judged against its acceptance criteria: a record without the criteria table means the
# verifier skipped them (verifier on 5342eef: the launcher checked the session and the mode, not this).
# Only when an issue names criteria: one written before the form, with no ACn ids, has none to judge and gets no table
# (verifier on 5f3ba7a: the check refused every rerun of such a branch).
ncrit=$( [ -s "$work/issues.md" ] && python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import record_review as rr; print(len(rr.issue_criteria(open(sys.argv[2], encoding="utf-8").read())))' "$here/scripts" "$work/issues.md" 2>/dev/null || echo 0)
if [ "${ncrit:-0}" -gt 0 ] && ! grep -q '^### Acceptance criteria' "$rec"; then
  echo "NO CRITERIA: the issues name $ncrit acceptance criteria, but the record for ${sha:0:7} has no criteria table." >&2
  KEEP=1; echo "kept $vdir for inspection" >&2
  exit 1
fi
echo "record: $rec"
# Keep the GPT review next to the record: scripts/automerge.py reads its tier, and $work goes away on exit. The verifier
# should have waited for Codex already; if it did not, this waits (Codex is limited to 25 minutes) so the file is final.
if [ -n "$codex_pid" ]; then wait "$codex_pid" || true; fi
if [ "$kind" = standard ] && [ "$(cat "$gpt_status")" = ran ]; then cp "$gpt" "$gate/$sha.gpt.md"; fi
paste_lines "$rec" "$gate/$sha.verify.json"
