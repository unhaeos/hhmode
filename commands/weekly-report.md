---
description: Weekly report formatted for the team's pre-meeting Google Form (Korean output, copy-paste ready)
argument-hint: [period like "2 weeks ago"] (default: 7 days ago)
---

# /weekly-report

Aggregate the last N days of work across all `~/projects/*` repos plus memo into the **team pre-meeting submission form** layout. **Korean output.**

Output covers only three sections: this-week's work, blockers / help-needed, next-week plan.
The other form fields (author, leave/remote, other, self-rating) are filled by the user — do not include them in output. Do not show form-field numbering (①②③④⑤⑥⑦) anywhere in output.

## 1. Resolve period

If `$ARGUMENTS` is empty, use `7 days ago`. Otherwise use it verbatim.
Compute today via `date +%Y-%m-%d` and start via `date -d '<period>' +%Y-%m-%d`.

## 2. Collect data (single Bash call)

```bash
SINCE="${ARGUMENTS:-7 days ago}"
AUTHOR=$(sed -n 's/^- git_author: //p' ~/projects/hhmode/local/identity.md)
START=$(date -d "$SINCE" +%Y-%m-%d)
echo "=== TODAY ==="; date +%Y-%m-%d
echo "=== SINCE ==="; echo "$START"
# untracked or modified files under a checkout whose mtime is inside the period
changed() {
  { git -C "$1" -c core.quotePath=false ls-files --others --exclude-standard; git -C "$1" -c core.quotePath=false diff --name-only HEAD; } 2>/dev/null |
    sort -u | while read -r f; do [[ -f "$1/$f" ]] && ! [[ $(date -r "$1/$f" +%Y-%m-%d) < "$START" ]] && echo "$f"; done | head -40
}
for d in ~/projects/*/; do
  name=$(basename "$d")
  [[ "$name" == _archive ]] && continue
  [[ -d "$d/.git" ]] || continue
  base=$(git -C "$d" rev-parse --verify -q main >/dev/null && echo main || echo master)
  echo "=== PROJECT: $name ==="
  echo "-- log ($base) --"
  git -C "$d" log "$base" --author="$AUTHOR" --since="$SINCE" --pretty=format:'%h %ad %s' --date=short 2>/dev/null
  echo
  echo "-- unmerged branch commits --"
  git -C "$d" log --branches --not "$base" --author="$AUTHOR" --since="$SINCE" --pretty=format:'%h %ad %D | %s' --date=short 2>/dev/null | head -40
  echo
  echo "-- changed in period, not committed --"
  changed "$d"
  echo "-- worktrees with uncommitted changes in period --"
  git -C "$d" worktree list --porcelain | sed -n 's/^worktree //p' | tail -n +2 | while read -r wt; do
    c=$(changed "$wt"); [[ -n "$c" ]] && { echo "[$wt] ($(git -C "$wt" branch --show-current))"; echo "$c"; }
  done
  echo "-- branches (non-main, with track) --"
  git -C "$d" for-each-ref --format='%(refname:short) %(upstream:track)' refs/heads/ | grep -v '^main\b\|^master\b'
  echo
done
```

Then `Read` `~/.claude/memo.md`.

## 3. Analysis

**This-week work** — from git log, unmerged branch commits, and uncommitted files:
- Unmerged branch commits whose subject already appears on main (a squash merge adds ` (#N)`) are the same work — count it once. Work that exists only on an unmerged branch is still this week's work; say it is not merged yet.
- A changed-in-period file that holds a measurement or evaluation result (run output, log, generated report) is an outcome: read it for the headline numbers. If the project's README or docs name a script that aggregates such results, run that script instead of computing your own. Before reporting a metric as missing, check the listed worktrees and unmerged branches for it. State the measurement date and the code it ran on (from the file's own metadata) — numbers only from what you read or ran.
- Group by project. If 5+ commits, cluster by prefix (`feat/`/`fix/`/`refactor/`/`docs/`/`chore/`) or topic, with `(N commits)` shown once on the first bullet.
- If <5, paraphrase naturally in Korean.
- Skip projects with no activity.

**Blockers**:
- memo `[blocker]` pending items.
- Branches with both `ahead` and `behind` (merge-stuck candidates).
- Else: `특이사항 없음`.

**Next-week plan**:
- Uncommitted changes, branches ahead of origin.
- memo priority order: `blocker` > `bug` > `todo` > `refactor`.
- 3–6 bullets, naturally written, grouped under `[프로젝트명]` headers like the work section.

## 4. Output format (form-ready)

**Critical**: each of the three wrapped in a fenced code block (```). Inside the block: only flat `- ` bullets — no nested indentation, no sub-bullets. (CLI markdown renderer indents nested lists, which leaks leading whitespace when copied.)

**Project grouping** (work and next-week sections): write the project name once, alone on its own line as `[프로젝트명]`, then that project's `- ` bullets directly below it, then a blank line before the next project. Never repeat `[프로젝트명]` at the start of each bullet. Header and bullets both start at column 0.

```
[국방 사이버 지식그래프]
- 첫 번째 성과 (N commits)
- 두 번째 성과

[보안 시뮬레이션 챗봇]
- 성과
```

```
# 주간보고 — <today> (금주: <start> ~ <today>)

> 각 코드블록 폼 해당 칸에 복붙. 나머지 칸은 직접 작성.

---

## 금주 주요 업무 내용 및 진행 현황

[fenced code block: `[프로젝트명]` header lines, each followed by flat bullets]

---

## 금주 애로사항 / 도움 필요

[fenced code block, or `- 특이사항 없음` inside]

---

## 차주 주요 업무 계획

[fenced code block]
```

## Rules

- Korean output.
- **Audience: non-technical (managers, other teammates).** This goes to a meeting. Strip from all three sections:
  - Branch names (`feat/x`, `main`), commit hashes, file/dir paths (`eval/`, `.gitignore`)
  - Implementation jargon: refactor / route / spec / migration / type / endpoint / merge / rebase
  - English identifiers — replace with plain words (e.g., "simulation_create 라우트" → "시뮬레이션 생성 기능")
- **Frame in impact / outcome**, not implementation. "What changed for the user/product", not "what was edited".
  - Bad: "vague check RULES 한 줄로 단순화"
  - Good: "사용자가 모호하게 요청해도 시뮬레이션이 일관되게 동작하도록 개선"
- 3–5 bullets per project. Group similar work, don't slice thin.
- `(N commits)` shown only on the first bullet of the work section.
- Do not dump raw commit messages.
- Blockers section is fact-based — no speculation / exaggeration. If empty, write `특이사항 없음`.
- Do not include any form-field numbering (①②③④⑤⑥⑦) in the output.
- If memo is empty, append to the work section: `(메모가 비어 있음. /mm <내용>으로 쌓아두면 애로사항이 자동으로 채워짐)`.
