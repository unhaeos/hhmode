---
description: Memo add / list / mark-done (~/.claude/memo.md)
argument-hint: <text> | (empty=list pending) | list | done <keyword>
---

# /mm

Memo file: `~/.claude/memo.md`

Branch on `$ARGUMENTS`. **All user-facing output in Korean.**

## 1. Empty `$ARGUMENTS` — list pending

Read memo, output pending (`- [ ]`) items grouped by tag (untagged go under "기타").
End with one line: `총 N개 미완 / M개 완료`.

## 2. `list` or `list all`

Output every item with two sections: 미완 / 완료.

## 3. `done <keyword>`

Find pending items whose content contains `<keyword>` (case-insensitive substring):

- **1 match** → use `Edit` to change `- [ ]` → `- [x]` and append ` (done: <today>)` to that line. Output: `✓ 완료 처리: <item>`.
- **2+ matches** → list candidates numbered, ask user which one.
- **0 matches** → output `매칭되는 항목 없음`.

Today's date via Bash: `date +%Y-%m-%d`.

## 4. Otherwise — add new item

Treat `$ARGUMENTS` as new memo content.

1. Today's date via `date +%Y-%m-%d`.
2. Auto-infer `tag` (only when obviously implied):
   - "버그" / "bug" / "에러" / "안 됨" / "안됨" / "고장" → `[bug]`
   - "리팩" / "refactor" / "정리" → `[refactor]`
   - "막힘" / "막혀" / "blocker" / "블락" → `[blocker]`
   - "공부" / "배우" / "learn" / "읽어볼" / "찾아볼" → `[learn]`
   - "해보" / "시도" / "실험" / "idea" / "아이디어" → `[idea]`
   - Otherwise an obvious action → `[todo]`
   - Ambiguous → omit tag
3. Auto-infer `project` if name appears in text:
   - "agent-api" / "agent api" → `[project:agent-api]`
   - "continual" / "tool calling" → `[project:continual-tool-calling]`
   - "vector search" / "vector-search" → `[project:vector-search-eval]`
4. Append after the `<!-- ITEMS BELOW -->` marker via `Edit`.
   Line format: `- [ ] YYYY-MM-DD [tag] [project:x] <content>` (omit absent parts).
5. Output a single line: `+ 추가됨: <full line>`.

## Rules

- Korean output, terse. No preamble.
- In list mode, just group by tag — no commentary.
- When adding, do not touch other items (rely on Edit's unique-match).

## Args
$ARGUMENTS
