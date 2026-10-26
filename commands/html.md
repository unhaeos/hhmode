---
description: Generate a self-contained editorial-style HTML page (clean white, neutral greys, wine+teal accents) — Korean-friendly
argument-hint: <free-form: title, content outline, data refs, accent overrides>
---

# /html

Generate a single self-contained HTML file styled like the canonical editorial reference at `~/projects/continual-tool-calling/eval_results/comparison.html`. **All user-facing prose Korean by default; English allowed where the user supplied English.**

## Resources

- **CSS template**: `~/.claude/templates/editorial.css` — read at runtime, inline into `<style>...</style>`. Don't redefine; just embed.
- **Reference page**: `~/projects/continual-tool-calling/eval_results/comparison.html` — read this when uncertain how a component is used (rubric / overview / query section / two-col compare).

## Pre-flight (always ask)

**Output path** — required. Ask the user where to save (e.g., `./report.html`, `~/reports/foo.html`). No default.

## Pre-flight (ask only if needed)

- **Accent colors** — defaults are wine `#7a2818` (`--ours`) + teal `#1d4a5c` (`--base`). Ask **only** when the content requires a third distinct categorical color (e.g., 3-way comparison, additional series). Otherwise stay silent.
- **Anything genuinely ambiguous** in the content/structure — ask. If not, just proceed.

## Process

1. Resolve output path (from args or ask).
2. `Read` `~/.claude/templates/editorial.css`.
3. Parse `$ARGUMENTS` for: kicker (small uppercase line), h1 (page title), sub (subtitle/dateline), section outline, data file references.
4. If data files are referenced (JSON / Markdown / CSV / text), `Read` them and use real values. **Never fabricate numbers/data.** If a section needs values that aren't supplied, ask the user.
5. Choose components based on content shape (catalog below).
6. Emit a single self-contained HTML:
   - `<!doctype html><html lang="ko">` (or `en` if content is English).
   - `<head>`: charset, viewport, `<title>`, `<style>` containing the inlined CSS.
   - `<body><div class="wrap">` containing `<header class="masthead">` then sections.
7. `Write` to the resolved path.
8. Print: absolute path, file size in KB, and the first ~8 lines of the rendered `<body>` content (sanity preview).

## Component catalog (when to use)

- **masthead** — every page. `kicker` (uppercase tag) → `<h1>` → `sub` (small grey).
- **meta-strip** — 2–6 key facts upfront (model, db, params, date). 4-col grid.
- **h2.section-title** — every major section divider. Uppercase, tracked, top-ruled.
- **table.overview** — numeric comparison rows; right-aligned, `tabular-nums`, optional `avg-row`.
- **table.rubric** — scoring criteria with anchors (low/mid/hi). Use `table-layout: fixed`.
- **table.scores** — per-item detailed scores with comment row beneath.
- **section.query** + `.q-head` + `.q-meta` + `.cols` two-col — for A/B side-by-side comparison detail.
- **.special-note** — left-rule banner for caveats / methodology footnotes.
- **details.narrative** — collapsible long prose (auto-shown closed; click to expand).

## Style discipline

- **Inline everything**: CSS in `<style>`. No external `<link>`, no `<script>`, no remote fonts.
- **Font stack** (already in CSS) covers Korean via "Noto Sans KR" / "Apple SD Gothic Neo".
- **Color palette** — keep CSS variables as defined unless overriding accents (then patch `--ours` / `--base` in a small `<style>` after the inlined CSS).
- **Tabular numerics** — always `font-variant-numeric: tabular-nums` on numeric cells (already class-encoded).
- **No emojis** in generated HTML unless user explicitly asks. Also avoid circled-letter glyphs (ⓐⓑⓒ) — they render as tofu boxes in headless/limited fonts; use plain `A.` `B.` or CSS badges.
- **3–6 sections** typical; more is fine if content warrants.

## Rules

- Output is one HTML file. No separate assets.
- Self-contained: open in any browser, no network needed.
- Korean content fully supported (charset utf-8 declared, font stack ready).
- Don't fabricate data. Ask or omit if missing.
- After Write, do not re-Read the file to "verify" — Write would have errored if it failed. Just print path + preview.

## Args
$ARGUMENTS
