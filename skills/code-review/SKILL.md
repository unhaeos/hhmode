---
name: code-review
description: Pre-commit code review pipeline — THREE fresh-context Claude subagents with different personas (bug hunter / attacker / architect) review independently, contested findings go through a structured attack-defense debate, and a fresh judge issues final verdicts (확정/권장/기각), so the user gets one adjudicated fix-list instead of raw disagreement. Use this skill whenever the user asks to "review my changes", "review this diff", "check my code before commit", "코드 리뷰", "리뷰해줘", "커밋 전에 봐줘", "PR 올리기 전 검토", "review the staged diff", or invokes /code-review with or without a path argument. The skill exists because a same-context LLM that helped write the code rubber-stamps it; only fresh-context delegation breaks that bias. Always trigger this skill instead of reviewing directly. One invocation is the whole review — do NOT repeat it multiple times per commit.
---

# Code Review

Run an objective code review before commit, push, or PR. The primary use case is the moment the user has staged changes and is about to type `git commit`.

> **History note**: originally a cross-model pair (Claude + Gemini CLI, same prompt — comparison required identical input). 2026-07-06 Google killed the gemini-cli individuals OAuth tier (`IneligibleTierError`, not fixable by CLI update) → Gemini removed. Same-model reviewers made the "identical prompt, N repeats" design redundant (empirically: 3 identical rounds produced near-identical Majors), so it became **3 persona-diverse reviewers in ONE invocation** — diversity covers blind spots that repetition cannot. The old "run the skill 3 times per commit" policy is retired. Gemini is fully retired from this pipeline (2026-07-16) — do not reintroduce it.

## The one rule

The actual review is performed by **three fresh-context Claude subagents in parallel**, each with a distinct reviewer persona:

- **A1 — 버그 헌터**: correctness, edge cases, concurrency, data loss. Reads the code asking "how does this break?"
- **A2 — 공격자**: security, input validation, authz, secrets, failure modes. Red-team lens.
- **A3 — 아키텍트**: design, duplication, over-engineering, test strategy, maintainability.

All three are launched via the `Agent` tool with `subagent_type: "general-purpose"`, in a SINGLE parallel batch. Each receives the SAME base material (Step 2) wrapped in the SAME verbatim Korean core template (Step 3) — **only the persona block differs**. The main agent never reviews the code directly — not even partially, not even for a one-line diff, not even if the user insists. There is no size-based bypass. Same-context review produces sycophantic rubber-stamps; delegation to fresh-context reviewers is the entire reason this skill exists.

**Why three personas instead of three repeats**: same-model repeats converge on the same findings; personas force different priors over the same diff, so the union is wider and genuine disagreements (not sampling noise) surface for user adjudication.

**Operational note**: one invocation = one complete review (~30-90s wall-clock). Do NOT run this skill multiple times per commit — the 3-round policy is retired; the three personas replace it. If the diff is comment-only or whitespace-only after filtering, fall through to Step 1 mode 5.

## Procedure discipline

Copy Steps 1-7 into your todo list verbatim before starting. A skipped step must be marked `skip: <reason>`. The report's first line is one of `PASS / ISSUES / BLOCKED` (see Step 7). Every 확정 verdict carries `measured` (the judge ran it) or `inferred` (the judge could not run it).

## Step 1 — Detect what to review

Walk the priority list. Stop at the first match. Announce the chosen mode in one line so the user knows what is being reviewed.

| Order | Condition | Target | Notes |
|---|---|---|---|
| 1 | `$ARGUMENTS` non-empty | the path arg (file or directory) | Skip git checks entirely |
| 2 | `git diff --cached` non-empty | staged diff | If `git diff` is ALSO non-empty, warn the user: "Reviewing staged only — N unstaged hunks in M files were not included." |
| 3 | `git diff` non-empty | working-tree diff | |
| 4 | upstream branch exists and differs from HEAD | branch diff vs upstream | Use `git rev-parse --abbrev-ref @{upstream}` first; fall back to `git symbolic-ref refs/remotes/origin/HEAD`; only as last resort try literal `main` / `master` / `develop` / `trunk` |
| 5 | none of the above match | call `AskUserQuestion` | Ask whether they want to review a specific path or skip |

**Preconditions:**
- If the cwd is not inside a git repo and no path argument was supplied, do not error opaquely — tell the user explicitly and ask for a path.
- If the diff becomes empty after filtering generated files (see Step 2), fall through to mode 5 instead of launching a subagent on nothing.

## Step 2 — Gather the material

**Intent first.** Write one paragraph stating what the change is trying to do, from the user's request, the commit message, and the diff. Reviewers get this paragraph; without it they flood the output with questions the author already answered.

**Repo review guide.** If the repo has a `REVIEW.md` (code owners' notes on what matters, what to ignore, what counts as failure), read it and pass it to all three reviewers and the judge verbatim. Recurring review findings in a repo belong in that file, not in this skill.


Collect what the subagents will see. Pass it in the `Agent` prompt — do not expect the subagent to run git commands itself. (For large material, assemble the filled core template into ONE scratchpad file and have each subagent Read it — byte-identical material for all three; the persona block goes in each Agent prompt, not in the shared file.)

- The full raw diff for the chosen mode (`git diff`, `git diff --cached`, or `git diff <upstream>...HEAD`).
- The current full content of every changed file via `Read`. For files larger than 1000 lines, read only ±60 lines around each changed hunk to keep context tight without blinding the reviewer to surrounding code.
- Branch name and the most recent commit message on HEAD, if available, as ambient context.
- Any reference material the user supplied (spec, 정의서, QA report) — reviewers without it flood the output with questions the spec already answers.

**Filter out** these path patterns from both the diff and the file reads — they produce noise without value:
`*.lock`, `*-lock.json`, `package-lock.json`, `yarn.lock`, `Cargo.lock`, `*.generated.*`, `*.pb.go`, `vendor/**`, `dist/**`, `build/**`, `node_modules/**`.

## Step 3 — Delegate to THREE persona reviewers in parallel

Dispatch all three in a SINGLE message — three `Agent` tool calls with `subagent_type: "general-purpose"`, `description: "Code review (<persona>) of <one-line target>"`.

Each reviewer's prompt = **persona block** (below, per reviewer) + **core template** (verbatim, placeholders filled, identical for all three).

**Pass the core template VERBATIM. Do not paraphrase. Do not translate the Korean to English. Do not summarize the diff — give them the raw diff. Do not add framing like "you helped write this code".**

**Why VERBATIM is load-bearing**: the Korean senior-engineer register is what suppresses the model's reflex to praise. Earlier English-translated versions of this prompt produced roughly 80% praise-only output across test diffs. The "you are seeing this code for the first time" framing is what makes the reviewers treat the code as a stranger's. The persona blocks are the ONLY sanctioned variation; anyone who "improves" the core template by translating, condensing, or rewording it will silently break the skill.

### Persona blocks (first paragraph of each prompt — replaces nothing, prepends)

**A1 — 버그 헌터:**
```
당신은 10년차 시니어 백엔드 엔지니어이고, 팀에서 "버그 헌터"로 불립니다. 코드를 보면 정상 동작보다 "이게 어떻게 죽는가"부터 봅니다 — 엣지 케이스, 경계값, off-by-one, 동시성 race, 부분 실패, 잘못된 상태 전이. 화려한 설계 얘기는 다른 리뷰어 몫이고, 당신의 임무는 실제로 터질 결함을 찾는 것입니다.
```

**A2 — 공격자:**
```
당신은 10년차 시큐리티 엔지니어이고, 레드팀 출신입니다. 이 코드를 공격자의 눈으로 봅니다 — 인젝션, 인증·인가 우회, 신뢰 경계를 넘는 입력, 검증 없는 외부 데이터, 시크릿 노출, 에러 경로에서 새는 정보, 악의적 입력으로 유발 가능한 실패 모드. 기능이 잘 도는지는 다른 리뷰어 몫이고, 당신의 임무는 악용 가능한 구멍과 방어 누락을 찾는 것입니다.
```

**A3 — 아키텍트:**
```
당신은 10년차 소프트웨어 아키텍트이고, 유지보수 지옥을 여러 번 겪어 까다로워졌습니다. 이 코드가 6개월 뒤에도 건강할지를 봅니다 — 중복, 어긋난 추상화 레벨, 기존 코드/유틸 재사용 기회, 과잉 방어·과잉 설계, 죽은 코드, 계약(스키마·API·프롬프트) 간 드리프트, 테스트 전략의 구멍. 한 줄짜리 버그 사냥은 다른 리뷰어 몫이고, 당신의 임무는 구조적 부채를 찾는 것입니다.
```

### Core template (identical for all three — replace only `<...>` placeholders)

```
누군가가 코드 리뷰를 부탁했습니다. 당신은 이 코드를 처음 봅니다 — 작성자가 누구인지, 어떤 의도였는지, 어떤 토론을 거쳤는지 모릅니다. 백지 상태에서 객관적으로, 비판적으로, 그러나 건설적으로 판단하세요.

READ ONLY: 파일을 수정하지 마세요. 테스트를 실행하지 마세요. 커밋하지 마세요. 어떤 도구도 사용하지 마세요. 당신의 출력은 아래 형식의 리뷰 텍스트 단 하나입니다.

**리뷰 대상**: <one-line target — e.g., "agent-api 레포의 스테이지된 변경 (3 files, +120 -34) — 곧 커밋될 예정">

**전체 diff**:
` ` `diff
<raw git diff output>
` ` `

**변경된 파일들의 현재 전체 내용** (맥락 파악용):

### <path/to/file1>
` ` `<lang>
<file content or ±60 lines around changes>
` ` `

---

다음 형식 그대로 한국어로 리뷰하세요. 칭찬 일색은 금지 — 정말 좋은 코드라도 개선 여지는 항상 있습니다. 트집 잡기도 금지 — 사소한 스타일 이슈는 묶어서 한 줄로만. 당신의 전문 분야를 우선하되, 분야 밖이라도 명백한 문제는 그냥 지나치지 마세요.

## 리뷰 요약
**대상**: ...
**총평**: 1-2 문장 + 머지 가능 여부 ( 그대로 OK / 수정 후 / 블로커 있음).

## Critical — 블로커
명백한 버그, 보안 취약점, 데이터 손실 위험, 프로덕션 장애 가능성. 없으면 "없음".
- **[file:line]** 문제 한 줄
 - **왜:** 이유
 - **수정:** 구체적 패치 (가능하면 코드 스니펫)

## Major — 수정 권장
설계 결함, 성능 함정, 동시성 이슈, 누락된 에러 처리, 테스트 부재. 같은 형식.

## Minor — 선택 사항
가독성, 네이밍, 작은 리팩토링. 묶어서 짧게.

## 잘된 점
정말 잘 짠 부분 1-3개. 없으면 생략.

## 작성자에게 질문
의도가 불분명한 부분, 확인하고 싶은 가정.

리뷰 원칙 (꼭 지킬 것):
- 파일명과 라인 번호를 반드시 명시.
- "왜" 문제인지 항상 설명. "이건 안 좋다"만으로는 부족.
- 수정 제안은 구체적으로. 가능하면 코드 스니펫.
- 테스트 없는 비자명 변경은 Major 또는 Critical로 분류.
- 리뷰 범위는 현재 diff로 한정 — 추가·수정된 코드(`+`)에만 집중. 삭제된 코드(`-`)·미변경 코드·맥락용으로 본 다른 파일의 문제는 코멘트 대상이 아님 (참조만).
- 불필요한 추상화, 과도한 방어 코드, 죽은 코드, 디버그 print/console.log/주석 잔여물 체크.
- 한국어로 답하세요. 간결하고 직접적으로. 지적은 명확하게, 근거와 함께.
```

In the template above, the literal characters `` ` ` ` `` represent backtick fences — when you actually send the prompt, replace each `` ` ` ` `` with three real backticks. (The escape exists only because this SKILL.md is itself markdown.)

## Step 4 — Triage (internal, not user-facing)

Match findings across the three reviews to route each item. This triage is metadata the main agent computes; it surfaces later inside the final report, never as opinion.

**Matching heuristic** (apply in order until two findings are matched):
1. Exact `file:line` match.
2. Same file, line numbers within ±10 lines → treat as same location.
3. Same file, same enclosing function/method/class name.
4. Same file, overlapping line ranges → match.
5. None of the above → solo finding.

**Routing** (Critical/Major only — Minor findings skip debate and pass straight to the final report as suggestions):
- **2+인 합의, same direction** → auto-confirmed ( candidate). No debate.
- **1인만 (solo Critical/Major)** → debate: attack → defense (Step 5).
- **정면 충돌** (same location, opposite conclusions or contradictory fixes) → debate: cross-rebuttal (Step 5).
- **severity 불일치** (2+ flagged, different tiers) → no debate; judge picks the tier (Step 6).

## Step 5 — Structured debate (contested items only)

NOT free-form discussion — free chat between agents collapses into agreement with whoever spoke first. Fixed turns only, dispatched in parallel across items:

- **Solo Critical/Major**: spawn a fresh 반박자 agent per finding — prompt (Korean): the finding + relevant diff/file excerpt + "이 지적을 반박하세요. 실제로 재현 가능한 결함인지, 전제가 맞는지, diff 범위 안의 문제인지 공격하세요. 확실히 반박되면 반박 근거를, 반박에 실패하면 '반박 실패'와 그 이유를 쓰세요." Then give the attack to the ORIGINAL reviewer for one defense turn — use `SendMessage` with that reviewer's agent id (context intact); if continuation is unavailable, a fresh agent with the original review quoted.
- **정면 충돌**: one rebuttal turn each way — side X's argument goes to side Y (`SendMessage`) and vice versa, in parallel. One turn only; no second round.

Each debate thread produces: finding + attack + defense (or rebuttal ×2). Collect these transcripts for the judge.

## Step 6 — Final verdict (fresh judge)

Spawn ONE fresh judge agent (no persona, `general-purpose`) — it has seen none of this before. Input: the diff, and per contested item the debate transcript; per auto-confirmed item the finding text. Prompt (Korean, same register): "당신은 리뷰 중재자입니다. 각 항목에 대해 판정하세요: 확정(커밋 전 수정 필요) / 권장(고치면 좋음) / 기각(사유 필수). 판정 기준: (1) 실제 재현 가능한 결함인가, (2) 현재 diff 범위의 문제인가, (3) 수정 비용 대비 가치가 있는가. severity 불일치 항목은 tier도 확정하세요. 공방에서 방어가 무너진 항목은 기각하고, 반박이 실패한 항목은 확정하세요. 각 판정에 한 줄 근거. 확정을 내리기 전에 그 항목을 실제로 재현하거나 관련 테스트를 실행하고, 쓴 명령과 출력 핵심 줄을 첨부하세요. 실행해서 확인한 판정은 `measured`, 실행이 불가능해 코드만 읽고 내린 판정은 `inferred`로 표시하세요. 실행 결과가 finding과 어긋나면 기각하고 그 출력을 근거로 적으세요."

The judge is the only agent in this pipeline allowed to run code. Reviewers stay READ ONLY (Step 3). Give the judge the repo path and the test command(s) you know of; it decides what to run per item.

The main agent NEVER issues verdicts itself — adjudication belongs to the fresh judge, not the context that ran the pipeline.

## Step 7 — Present the final report

Lead with the verdict list (this is what the user acts on), then appendices:

```
**판정: PASS | ISSUES | BLOCKED** (PASS = 확정 0건 / ISSUES = 확정 1건 이상 / BLOCKED = 리뷰 대상 없음 또는 판정자가 실행 불가)

## 최종 판정
### 확정 — 커밋 전 수정
- [file:line] <finding 한 줄> (제기: A1 / 판정 근거 한 줄 / measured|inferred: <명령 또는 사유>)
### 권장
- ...
### 기각
- [file:line] <finding 한 줄> (제기: A2 / 기각 사유 한 줄)
### Minor 제안 모음
- <persona별 minor를 묶어 짧게>

---
<details>
## 부록 A — 원문 리뷰 3편 (verbatim)
### A1 — 버그 헌터
<verbatim>
### A2 — 공격자
<verbatim>
### A3 — 아키텍트
<verbatim>

## 부록 B — 공방 기록 (contested items)
- [file:line] 공격 요지 / 방어 요지 / 판정
</details>
```

Reviews in the appendix are **verbatim** — do not summarize, soften, or reorder them. The verdict list restates each finding in ONE line (that is the judge's output, not the main agent's rewording).

### Follow-up handling

When the user pushes back on a verdict or finding, do NOT answer from the main context. Route the question to the persona that raised it or the judge via `SendMessage` (context intact) or a new `Agent` call with the relevant transcript quoted. The main agent never adjudicates.

## Convergence

One invocation is one review. If the user fixes findings and asks again, review only the new diff, do not re-report findings already raised, and after the third round say so and ask the author to reconsider the approach instead of running a fourth. (Claude Code team: an agent author and agent reviewer cycled 50+ times overnight; ~59% of re-flagged code was unchanged since the first pass.)

## Common mistakes

- Don't: Reviewing the code yourself in the main context, even partially
 Do: Always delegate to the THREE persona reviewers, no exceptions
- Don't: Running the skill multiple times per commit (old 3-round policy)
 Do: ONE invocation = the complete review; the three personas replace repetition
- Don't: Running fewer than three reviewers "to save time", or sequentially
 Do: Three personas, single parallel batch
- Don't: Rewording the core template, or giving personas different diffs/material
 Do: Core template verbatim + identical material; ONLY the persona block varies
- Don't: Translating the Korean template to English when "improving" the skill
 Do: Pass it raw; the Korean register is load-bearing and was tested
- Don't: Skipping delegation for a "trivial" one-line change
 Do: No size-based bypass
- Don't: Telling reviewers "you helped write this" or "this is your own code"
 Do: Reviewers receive the diff with no authorship context
- Don't: Picking staged-diff mode without warning the user that unstaged hunks also exist
 Do: Always announce the chosen mode and flag any excluded changes
- Don't: Softening, summarizing, or reordering reviewer output in the appendix
 Do: Appendix reviews are verbatim; only the judge's one-liners appear in the verdict list
- Don't: Letting contested items debate in free-form chat, or running extra rebuttal rounds
 Do: Fixed turns only: attack → defense (solo) / one cross-rebuttal each (충돌)
- Don't: The main agent issuing or overriding verdicts (확정/기각)
- Don't: The judge issuing 확정 from reading alone when a test or repro was runnable
 Do: Run it, attach command + output, label `measured`; only unrunnable items are `inferred`
- Don't: Omitting the `PASS / ISSUES / BLOCKED` first line, or inventing a fourth word
 Do: Adjudication belongs to the fresh judge agent only
- Don't: Sending 2+인 합의 or Minor items into the debate stage
 Do: Debate is for solo Critical/Major and 정면 충돌 only — everything else routes straight to the judge/report
- Don't: Answering follow-up questions about specific findings from the main context
 Do: Route them back to the originating persona or the judge via SendMessage / fresh Agent calls
- Don't: Loading the entire codebase as "context" for the reviewers
 Do: Diff plus directly affected file content only
- Don't: Reviewing generated files like `package-lock.json` or `dist/`
 Do: Filter them out before constructing the prompt
