---
description: Monday plan — theme-grouped week-ahead plan anchored to the roadmap docs, not just git/memo (Korean output)
argument-hint: (none)
---

# /monday-plan

Compile a start-of-week plan grouped into **a few big themes**, each anchored to the project's
actual roadmap/plan docs — not a day-by-day calendar, not a flat file-level dump. **Korean output.**

The plan is for the user themself (start-of-week priming). Implementation jargon (branch names,
file paths, tool names) is fine here.

## 1. Collect data

### 1a. Git + memo (single Bash call)

```bash
AUTHOR=$(sed -n 's/^- git_author: //p' ~/projects/hhmode/local/identity.md)
echo "=== TODAY ==="; date +%Y-%m-%d
for d in ~/projects/*/; do
  name=$(basename "$d")
  [[ "$name" == _archive ]] && continue
  [[ -d "$d/.git" ]] || continue
  echo "=== PROJECT: $name ==="
  echo "-- status --"
  git -C "$d" status --short
  echo "-- branches (non-main) + ahead/behind vs main --"
  for b in $(git -C "$d" for-each-ref --format='%(refname:short)' refs/heads/ | grep -v '^main$\|^master$'); do
    cnt=$(git -C "$d" rev-list --left-right --count main..."$b" 2>/dev/null)
    echo "$b  (behind/ahead vs main: $cnt)"
  done
  echo "-- recent (last 7 days) --"
  git -C "$d" log --author="$AUTHOR" --since='7 days ago' --pretty=format:'%h %s' | head -20
  echo "-- plan/roadmap docs (most recently edited first) --"
  ls -t "$d"docs/*.md "$d"docs/*.html 2>/dev/null | grep -iE 'plan|roadmap|spec|catalog|draft|transition' | head -10
  echo
done
```

Then `Read` `~/.claude/memo.md`, and read any recalled `project` memory already in context
(roadmap, collaboration agreements, current-phase decisions).

### 1b. Read the plan docs — do NOT skip this

The git log + memo tell you *what was touched*, not *what comes next*. The roadmap does.
Identify the **active project** (most recent commits / current branch) and `Read` its 1–2 most
relevant plan docs surfaced above (the roadmap + the latest week/phase draft). Anchor the plan's
themes to that roadmap's next steps, not to tasks invented from git diffs.

## 2. Verify before asserting

Memory and plan-draft claims are point-in-time and may be stale. Before listing something as a
task, spend a few cheap targeted checks to confirm it's still real:

- A memo/memory citing `file.py:line` as buggy → grep/read that line; is it still so?
- "X not yet built" → `ls`/`grep` for it; maybe it already exists.
- "branch not merged" → the ahead/behind count from 1a already tells you.

State what you verified ("ui_builders.py 확인 — 아직 없음"), so the plan reflects current reality.

## 3. Group into a few big themes

Do **not** produce a Mon/Tue/Wed calendar and do **not** lead with a flat per-file list.
Cluster the work into **3–5 themes** (A, B, C, ...), each being one coherent chunk of the roadmap.
For each theme, classify its status so the user sees what they can actually start:

- **본줄기 / actionable** — no external dependency, can be driven solo this week.
- **blocked** — gated on someone/something (another team's validation, a sync with a collaborator, the user's own input, an upstream API). Name the blocker explicitly.
- **보류 / kept** — intentionally parked; mention in one line, don't expand.

Order themes by: actionable main-line work first, blocked/parked last. Don't pad the plan with
inactive projects or tasks the user has set aside — note them in a single trailing line.

## 4. Output format

Each theme = **a one-line plain-language headline** (what & why), then the file/code/tool detail
**below it as a single `>` blockquote line**. No checkboxes — they hurt readability. Headline
first, granularity second.

```
# 할 일 정리 (<today>)

> <one-line roadmap context: where we are, what the next milestone is>

## A. <headline — plain language, includes status tag like "본줄기" / "blocked: <blocker>" / "보류">
<1–2 sentences: what this theme is and why it's here / why it's blocked.>

> <detail: concrete files, tools, specs, order of operations — packed into one blockquote line>

## B. <headline …>
...

---

**순서**: <which theme is the real focus this week, what's next, what's waiting on whom — one or two lines>
```

Notes on the format:
- Skip a `## Memo` section as its own block — fold memo items into whichever theme they belong
  to (a memo bug becomes its own theme, etc.). Memo is an input, not an output section.
- If a theme is blocked on the user's own action, say so plainly so they know the ball is in their court.
- End with a concrete offer when there's read-only work you can do now (a code/routing review, a
  staleness check) — but only offer; don't run it.

## Rules

- Korean output. Code/commands/identifiers stay English.
- **Themes must trace to collected data + the roadmap docs** — no inventing tasks from thin air,
  and no ignoring the roadmap in favor of git-diff guesses.
- If memo is empty, note it once: `(메모가 비어 있음. /mm <내용>으로 쌓아두면 다음 플랜에 반영됨)`.
- Distinct from `/weekly-report` (which targets non-technical readers and looks backward); this
  view is forward-looking and for the user themself, so technical detail is welcome.
