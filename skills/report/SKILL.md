---
name: report
description: House style for written deliverables (reports, plans, write-ups, design notes) as HTML artifacts in an academic tech-report register. Load whenever the user asks for a document to read: "리포트 만들어줘", "정리해서 문서로", "계획서 써줘", "write this up", "make a report". Forbids card/badge/icon-heavy design; the document is body text plus tables.
---

# Report standard

This format was fixed after repeated correction by the user. Do not add decorative design outside it.

## Principle

**A document is read, not scanned.** A report is not a dashboard. Tables carry the facts; prose says only what a table cannot. Every other visual device is noise. The reference image is an arXiv paper or tech report.

**Length.** At most three paragraphs per section. Anything that fits a table goes in a table and is not repeated in prose. Sections like design or configuration are better as one table than as paragraphs. If the document has more paragraphs than tables, it over-explains.

## Forbidden (AI-slop patterns)

- Stat card grids (big number plus label, three in a row)
- Tags, badges, pills
- Step-card flows (boxes for steps; use an `<ol>`)
- Eyebrow labels (uppercase, letter-spaced kickers)
- A metadata line at the top of the document, such as `2026-09-30 · 로컬 Qwen · 198문항 1회 · eval/kgqa`. Date and environment go in the colophon or the first paragraph.
- Question-form titles, for the document and for sections: "지식그래프가 검색보다 나은가", "무엇을 재려 했나", "왜 중요한가". They make the reader wait for an answer.
- Activity-list subtitles: "여섯 가지를 나란히 재고, 격차를 둘로 나눴다". A subtitle states a conclusion or a key number.
- Emoji or icon section markers
- Gradients, cards inside cards, left-bar callouts in quantity
- Background boxes in quantity. A summary is a lead paragraph plus a list, not a box.

## Layout and type

- One column, `max-width: 720px`, generous margins (`padding: 56px 24px 96px`)
- Fonts: `Noto Sans KR` (Google Fonts, weights 400/600/800) plus `JetBrains Mono` for numbers and code
- Rendering: `html { -webkit-font-smoothing: antialiased; text-rendering: optimizeLegibility; }` is required; it fixes jagged Korean webfont rendering. Body 16px or larger, `line-height: 1.75`, `word-break: keep-all`
- Heading scale: h1 27px/800, h2 19px/800 (section number in a leading `<span>`, muted color), h3 16px/800
- Document start: h1, one-line subtitle, then a **heavy rule** (2.5px). No metadata line. Date, model, sample size are stated as facts in the colophon or the summary.
- Document end: heavy rule, then the colophon (reproduction materials, file paths, small muted text)

## Color

- Effectively monochrome: background `#FFFFFF`, ink `#191C20`, mute `#5E6672`, one link color `#1849A9`
- Emphasis is `<strong>` (800) and `<mark>` (pale yellow `#FFF3C2`) only. Status and verdicts are **text** ("기각", "완료", "대기"), not color.
- Dark mode via CSS variables with three states: `:root` light, `prefers-color-scheme: dark` guarded by `:root:not([data-theme="light"])`, and `:root[data-theme="dark"]`. Give `body` an explicit background.

## Tables (booktabs style)

- No vertical rules. 2px rule on top, 1px under the header, 2px under the last row. Very light 1px between rows.
- Header small (13.5px), muted, weight 600
- Caption above the table, left-aligned: `<caption><b>표 N.</b> 설명</caption>`
- Numeric cells: `font-family: JetBrains Mono; font-variant-numeric: tabular-nums`
- Best row or cell marked by **weight (800)**, not background
- Each table in an `overflow-x: auto` wrapper
- Statistical footnotes (CI, p-values) under the table in a `footnote` class (13.5px, muted)

## Content order

1. Title and subtitle
2. **Summary**: a lead paragraph starting with "요약." (two or three sentences of the main claim, key numbers in `<mark>`), then a dash list of two to four key results
3. Numbered sections: design, results (table-centered), analysis or mechanism, **verification (the list of things you tried to refute: a three-column table of objection / method / result, including what was withdrawn)**, comparison to prior work, limitations, next steps
4. Colophon: reproduction file paths, date and environment

### Writing titles

**The document title is a noun phrase naming the subject.** No question marks.

| Avoid | Use |
|---|---|
| 지식그래프가 검색보다 나은가 | 지식그래프 조회와 산문 검색 6조건 비교 |
| 왜 파이프라인이 느린가 | 적재 파이프라인 병목 분석 |

**The subtitle states the conclusion or the key number.** It does not list what was done.

| Avoid | Use |
|---|---|
| 여섯 가지를 나란히 재고, 격차를 둘로 나눴다 | 격차의 절반은 턴 수에서 나온다. 구조가 더하는 몫은 +0.129다 |

**Section titles are declarative noun phrases.** The title alone should say what the section covers.

| Avoid | Use |
|---|---|
| 무엇을 재려 했나 | 조건 설계 |
| 왜 이렇게 했나 | 공정성 통제 |
| 어떻게 해결했나 | 수정 내역 |
| 무엇을 알게 됐나 | 효과 분해 |
| 앞으로 무엇을 할까 | 다음 단계 |

A result may appear in a section title: "지식그래프가 지는 칸", "예상과 달랐던 것". A title that states the section's conclusion is better.

## Sentences

- Conclusion first, evidence second. Numbers can sit in prose, but the basis of a comparison is a table.
- **Do not turn interpretation into prose.** Write "0.415 → 0.562" rather than "격차의 절반은 턴 수에서 나온다". Do not pre-digest the reader's interpretation.
- **No inverted or emphatic word order.** "조건은 여섯이다" becomes "여섯 조건을 비교했다" or a table caption.
- Do not hide negative results, retractions, or limitations. They get their own section.
- Explain a technical term in one line on first use, e.g. "slip(실행 실수)".

## Sentence review (required): the geulsseuja pipeline

Before wrapping the body in HTML, run it through steps 3 to 5 of the `geulsseuja` skill (`~/.claude/skills/geulsseuja/SKILL.md`). A plain layout does not help if the sentences read as machine-written.

1. Write the body paragraphs as Markdown or plain text first (`/tmp/<name>_body.md`).
2. Run `uv run --project ~/projects/geulsseuja geulsseuja lint /tmp/<name>_body.md`. Fix only the flagged sentences until the "AI 티" section is empty and the verdict is "사람 글 범위" (at most three passes).
3. Give the body alone to a subagent with no conversation context for a blind critique (geulsseuja step 5 prompt). Fix anything rated "상".
4. Only then assemble the HTML. Note the linter score and critique result in one colophon line.
