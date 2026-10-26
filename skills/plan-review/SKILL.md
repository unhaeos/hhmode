---
name: plan-review
description: Pre-implementation plan review delegated to TWO fresh-context Claude subagents in parallel — a pragmatic executor and a skeptical architect — so the plan is stress-tested by two independent strangers with different lenses and disagreements surface. Use this skill whenever the user asks to "review my plan", "check this design", "plan 리뷰", "계획 리뷰해줘", "구현 전에 검토", "design review", or invokes /plan-review with or without a path argument. The skill exists because a same-context LLM that helped draft the plan rubber-stamps it; only fresh-context delegation breaks that bias, and two persona-diverse reviewers reduce single-lens blind spots. Always trigger this skill instead of reviewing directly.
---

# Plan Review

Review implementation plans, refactoring strategies, or feature designs before coding begins. Uses **two fresh-context Claude subagents in parallel**, each with a different review lens, to catch blind spots the planner missed.

> **History note**: originally a cross-model pair (Claude subagent + Gemini CLI, same prompt). 2026-07-06 Google killed the gemini-cli individuals OAuth tier (`IneligibleTierError`, not fixable by CLI update) → Gemini fully retired. Same-model identical-prompt reviewers are near-redundant (empirically, per code-review), so the pair became **two persona-diverse Claude subagents** — a pragmatic executor and a skeptical architect. Lens diversity covers blind spots that a second identical model could not.

## The one rule

The actual review is performed by **two fresh-context subagents in parallel**, never by the main agent:

- **Reviewer A — 실무 실행자**: lens = execution order, dependency breakage, rollback difficulty, test strategy, incremental applicability.
- **Reviewer B — 회의적 아키텍트**: lens = scope appropriateness, design alternatives, missing considerations, over/under-engineering, long-term risk.

Both are `Agent` calls with `subagent_type: "general-purpose"`. The main agent never reviews the plan directly. No bypass for "simple" plans.

**Why two lenses**: a single fresh-context reviewer still has one perspective. Two persona-diverse reviewers surface issues one lens would miss and expose disagreements for explicit user adjudication.

## Step 1 — Detect what to review

Check in this order:

1. **Argument given** — user passed a specific plan description or file path. Use that.
2. **Recent plan in conversation** — locate the most recent plan, task list, or design proposal. **Do NOT summarize it.** Same-context summarization is exactly the bias this skill exists to avoid — paraphrasing the plan in the main context softens the very weaknesses fresh reviewers should see. Instead: extract the plan text verbatim and show it to the user with `AskUserQuestion`: "이 텍스트를 plan으로 보고 리뷰 보낼게요. 맞나요? (네 / 다른 부분 / 직접 입력)". Only proceed after user confirms.
3. **Nothing found** — use `AskUserQuestion` to ask what they want reviewed.

Announce what you're reviewing in one line.

## Step 2 — Gather context

Collect for both subagents:

- The full plan text (bullet points, task list, design description — whatever form it takes).
- Current state of key files that the plan will modify (via `Read`). Only include files directly referenced in the plan. For files over 500 lines, include only the relevant sections.
- Brief repo description (main language, framework, what the app does) so the reviewer has context.

## Step 3 — Delegate to TWO fresh-context reviewers in parallel

Dispatch BOTH reviewers in parallel — single message, two `Agent` tool calls. Each gets the SAME plan/context block; they differ ONLY in the persona/lens line at the top.

- **Reviewer A**: `Agent`, `subagent_type: "general-purpose"`, `description: "Plan review (실행 렌즈) of <one-line target>"`, prompt = template below with the A persona line.
- **Reviewer B**: `Agent`, `subagent_type: "general-purpose"`, `description: "Plan review (설계 렌즈) of <one-line target>"`, prompt = template below with the B persona line.

Pass the template **verbatim** — do not translate, paraphrase, or summarize. The Korean register is load-bearing, same reasoning as code-review.

```
<PERSONA LINE — see below>

당신은 이 프로젝트를 처음 봅니다. 백지 상태에서 객관적으로, 비판적으로, 그러나 건설적으로 판단하세요.

READ ONLY: 파일을 수정하지 마세요. 코드를 실행하지 마세요. 당신의 출력은 아래 형식의 리뷰 텍스트 단 하나입니다.

**프로젝트 배경**: <brief repo description — language, framework, what it does>

**리뷰 대상 계획**:
<full plan text>

**관련 코드 현재 상태**:

### <path/to/file1>
` ` `<lang>
<file content or relevant sections>
` ` `

---

다음 형식으로 한국어 리뷰하세요. 읽기 좋게 작성하세요 — 항목마다 충분한 줄바꿈, 들여쓰기, 구분선을 활용하세요.

---

## 계획 리뷰

**대상**: (리뷰 대상 한 줄 요약)

**총평**: 2-3 문장. 전체 방향이 맞는지 + 실행 가능 여부.
(✅ 이대로 진행 / ⚠️ 조정 필요 / 🛑 재설계 필요)

---

## 🛑 블로커 — 이대로 진행하면 안 되는 것

진행 시 깨지거나 되돌리기 어려운 문제. 없으면 "없음".

각 항목은 이 형식으로:

### 문제 한 줄 요약
왜 문제인지 2-3 문장 설명.

**대안**: 구체적 제안.

---

## ⚠️ 개선 권장 — 하면 확실히 나아지는 것

놓친 고려사항, 더 나은 순서, 빠진 단계, 과도한 범위 등.

각 항목은 이 형식으로:

### 포인트 한 줄
설명 2-3 문장.

---

## 💡 대안 제안

계획과 다른 접근법이 있다면. 없으면 생략. 블록인용(`>`) 쓰지 말고 일반 텍스트로.

---

## ✅ 잘된 점

계획에서 좋은 판단 1-3개. 불릿(`-`)으로.

---

## 🤔 확인 질문

계획에서 의도가 불분명한 부분, 확인하고 싶은 가정. 번호 매겨서.

---

리뷰 원칙:
- 구체적으로 — "이건 좀 그렇다" 금지. 파일명, 함수명, 구체적 상황을 명시.
- 당신의 렌즈에 해당하는 위험을 특히 파고들되, 명백한 다른 문제도 놓치지 마라.
- 계획의 순서가 맞는지 봐라 — 먼저 해야 할 걸 나중에 하면 삽질.
- 한국어. 토스/당근 말투 — "~해요" 체. 친근하지만 핵심은 정확하게. 날카로운 지적도 부드럽게 전달.
```

In the template, `` ` ` ` `` represents triple backtick fences — replace with real backticks when sending.

**Persona lines** (put one at the very top of each reviewer's prompt, replacing `<PERSONA LINE>`):

- **Reviewer A**: `당신은 10년차 시니어 백엔드 엔지니어입니다. 누군가가 구현 전에 계획 리뷰를 부탁했습니다. 당신의 렌즈는 '실행'입니다 — 작업 순서와 의존성(A를 바꾸면 B가 깨지나?), 되돌리기 난이도, 테스트 전략, 점진적 적용 가능성을 최우선으로 봅니다.`
- **Reviewer B**: `당신은 10년차 시니어 소프트웨어 아키텍트입니다. 누군가가 구현 전에 계획 리뷰를 부탁했습니다. 당신의 렌즈는 '설계'입니다 — 범위 적절성(너무 크거나 작지 않나?), 더 나은 대안 접근, 빠진 고려사항, 과잉/과소 설계, 장기 유지보수 리스크를 최우선으로 봅니다.`

Both Claude subagents reliably follow the Korean format — no drift fallback needed.

## Step 4 — Present both reviews verbatim, then a convergence/divergence map

Output BOTH reviews **verbatim**. Do not summarize, soften, reorder, or add commentary inside either review's body.

Format:

```
## 🅰 리뷰어 A — 실무 실행자
<Reviewer A's full output, verbatim>

---

## 🅱 리뷰어 B — 회의적 아키텍트
<Reviewer B's full output, verbatim>

---

## 🔀 합의·이견 맵
<see rules below>
```

### Convergence/divergence map — rules

This map is the ONLY part the main agent authors. It is metadata, not a paraphrase. **Never restate either reviewer's finding text.** Use only the reviewers' own headings/identifiers and severity tags.

**Matching heuristic** (apply in order until two findings are matched):
1. Exact heading-text match (modulo trivial whitespace/punctuation).
2. Same plan section / step / file referenced (use shared identifiers — file path, plan step number, function name).
3. Both findings target the same conceptual concern (e.g., "rollback strategy missing" vs "no revert path") — only match if both reviewers explicitly named the same artifact.
4. None of the above → list separately.

**Categories**:
- **양쪽 다 지적**: same item (per heuristic) flagged at the same severity tier (블로커 / 개선 권장). High confidence. Cite both headings.
- **A만 지적**: items unique to Reviewer A (cite heading text only).
- **B만 지적**: items unique to Reviewer B (cite heading text only).
- **위치 표기 차이**: same conceptual item but reviewers cited different artifacts/headings — list both refs with one-line note.
- **정면 충돌**: same area where the two reviewers reach opposite conclusions (A 블로커 / B explicitly approves, or contradictory alternatives). One-line "A: <heading> / B: <heading>" — neutral phrasing.
- **severity 불일치**: same item, different tier (A: 블로커, B: 개선 권장).

If a section is empty, write "없음".

### Discussion-to-decision (only when there is conflict)

If 정면 충돌 is non-empty, append:

```
## 🗳 결정 요청
정면 충돌 항목은 한쪽만 옳거나 두 시각이 다른 가정을 깔고 있어요. 사용자 판단이 필요합니다:
- [item] — 어느 쪽으로 갈까요?
  - 한 번만 양측 defense 듣고 싶으면 → 해당 reviewer(들) 재질문 (depth=1)
  - 더 깊은 다라운드 토의가 필요하면 → 각 reviewer에 라운드를 이어 붙여 재질문 (depth≥2)
```

Do NOT pick a winner from the main context. The whole point is to expose disagreement, not paper over it.

### Sign-off

> ━━━━━━━━━━━━━━━
> — Vex (A: 실무 실행자 / B: 회의적 아키텍트)

### Follow-up handling

When the user pushes back on a specific finding, route the question to the relevant reviewer(s) via a new `Agent` call (refinement turn with prior review + user question):

- Finding from Reviewer A only → new A-persona `Agent` call.
- From Reviewer B only → new B-persona `Agent` call.
- Both flagged it, or 정면 충돌 involved → query both in parallel, present each side's defense without choosing.

Same fresh-context discipline. The main agent never adjudicates the review itself.

## Common mistakes

- ❌ Reviewing the plan in the main context, even partially → always delegate to BOTH
- ❌ Running only one reviewer → no single-reviewer fast path
- ❌ Same persona line for both → A and B must carry different lenses; only the plan/context block is shared
- ❌ Sequential A then B → dispatch in parallel, single message
- ❌ Translating the Korean prompt template to English → load-bearing register
- ❌ Summarizing the plan in main context before sending to reviewers → Step 1 mode 2 forbids it; show verbatim and confirm with user
- ❌ Paraphrasing findings in the convergence map → metadata only
- ❌ Picking a winner in 정면 충돌 from the main context → surface to user, do not adjudicate
- ❌ Answering follow-ups from the main context → route back to the originating reviewer(s)
