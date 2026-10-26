---
description: Slack·Gmail(받은 것+내가 보낸 약속)을 AI가 훑어 할 일만 골라 memo.md
argument-hint: (empty=최근분) | days=N | emoji:<name> (Slack 이모지 보조모드)
---

# /collect-todos

토스식 "메시지 → 할 일"을 **AI 필터**로. Slack·Gmail에서 **내가 처리/응답해야 하는 것**과
**내가 하겠다고 약속한 것**만 골라 "내가 적었을 법한" 짧은 할 일로 `~/.claude/memo.md` 에 넣는다.
나머진 버린다. 표시는 `~/projects/todo-widget/server.py`.

- 내 Slack user_id: **U09EREVN6G7** / 내 이메일: **hh.seo@78researchlab.com**

## 모드
- 기본(인자 없음): 아래 4소스 자동 필터.
- `days=N`: 수집 윈도우 최근 N일(기본 7일).
- `emoji:<name>`: Slack 이모지 보조모드(`hasmy::<name>:`).

## 절차

1. **윈도우 결정.** `~/projects/todo-widget/.lastrun` 있으면 그 이후, 없으면 최근 7일(`days=N` 우선).
   오늘: `date +%Y-%m-%d`. Slack은 `after:YYYY-MM-DD`, **Gmail은 `after:YYYY/MM/DD`(슬래시)**.

2. **중복 방지용 출처 읽기.** memo.md 에서 `↗<url>` 이 포함된 줄들의 URL을 모은다(완료 `[x]` 항목 포함) = dedup 키.
   URL이 달라도 기존 항목(완료 포함)과 **같은 건의 재언급**이면 스킵.

3. **4소스 검색.**
   - **(a) Slack 받은 것** — `slack_search_public_and_private`, query `to:me after:<d>`,
     sort=timestamp desc, limit 20, include_context false. 멘션 부족하면 `<@U09EREVN6G7> after:<d>` 추가.
   - **(b) Slack 내가 보낸 것** — query `from:me after:<d>`. (내 약속/커밋 찾기)
   - **(c) Gmail 받은 것** — `search_threads`, query
     `in:inbox after:<d> -category:promotions -category:social -category:forums`.
     제목/snippet으로 판단하되 애매하면 `get_thread`로 본문 확인.
   - **(d) Gmail 내가 보낸 것** — `search_threads`, query `in:sent after:<d>`.
   응답이 커서 파일로 떨어지면 거기서 발신자/시각/내용/Permalink(또는 threadId)만 뽑는다.

4. **판단 — 소스별로 다르다(핵심).**
   - **받은 것 (a·c)**: 살림 = 나한테 온 *요청·질문·할당·확인요청·마감*(내가 행동해야 풀림).
     버림 = FYI·뉴스레터·알림·자동발송·영수증·잡담·인사·이미 끝난 대화.
   - **내가 보낸 것 (b·d)**: 살림 = **내가 하겠다고 한 약속/커밋**("~하겠습니다/하도록 하겠습니다/할게요/
     작업하겠습니다/수정하겠습니다/처리하겠습니다/보낼게요/정리해서 드릴게요", 내가 스스로 잡은 마감·후속작업).
     - 한 메시지에 **번호로 나눠 여러 약속**을 했으면 **각각 별도 할 일**로 살린다.
     - **"산출물이 약해 보인다"고 함부로 버리지 말 것** — 내가 한 약속은 기본적으로 내 할 일이다(놓치면 내가 손해).
     - 버림 = 단순 답변·동의·인사·잡담·이미 완료한 것, 그리고 **"~할까요?/원하시는 바 있나요?"처럼
       상대에게 되묻는 것**(공이 상대에게 넘어간 거라 내 할 일 아님).
   - **애매할 때**: 받은 것은 버린다(노이즈 우선). 하지만 **내가 한 약속은 애매해도 살리는 쪽**으로.
   - 특정 인물/문구 하드코딩 금지(일반 기준).

5. **우선순위 부여.** 마감 임박·긴급 = `[P1]`, 일반 요청·약속 = `[P2]`, 가벼운/덜 급한 것 = `[P3]`.

6. **살린 것만 추가.** memo.md `<!-- ITEMS BELOW -->` 뒤에:
   ```
   - [ ] <메시지날짜 YYYY-MM-DD> [Pn] [slack|gmail] <짧은 제목> — <상세(선택)> ↗<permalink>
   ```
   - **제목**: 딱 보면 아는 `[대상]+[동사]`(~25자), 명령형, 원문 복붙 금지. 마감 있으면 `(M/D 마감)`.
     내가 보낸 약속은 약속 그대로("OO 정리해서 보내기"). 수식어·배경은 상세로.
   - **상세(선택)**: ` — ` 뒤에 **완결된 문장으로 풀어서** — 배경(누가·무슨 맥락) → 해야 할 일 → 조건·마감 순.
     전보체 나열(`·`로 단어 압축, 약어 뭉치) 금지 — 맥락 모르는 사람이 읽어도 이해되게. 없으면 제목만.
     세부 항목이 여러 개(①② 등 번호 나열)면 한 문장에 욱여넣지 말고 **항목마다 ` ⏎ ` 구분자**로
     나눠 적기(위젯이 줄바꿈으로 표시. memo.md 물리 줄은 그대로 한 줄이어야 함 — 실제 개행 금지).
   - 제목 본문엔 ` — ` 금지(구분자). **호칭**: 이름 대신 `'OO님'`, **남성엽 → 소장님**(제목·상세 양쪽).
   - 태그: Slack 출처면 `[slack]`, Gmail 출처면 `[gmail]`.
   - `↗<permalink>` 필수. Slack=메시지 permalink, **Gmail=`https://mail.google.com/mail/u/0/#all/<threadId>`**.
   - 2번 집합에 이미 있는 url 은 건너뛴다.

7. **`.lastrun` 갱신** — 오늘 날짜 기록.

8. **출력(한국어).**
   - `+ 살린 N건` — 추가한 할 일 한 줄씩 (소스 표시: 슬랙받음/슬랙약속/메일받음/메일약속)
   - `– 버린 M건` — "출처·발신자: 한줄요지 (버린 이유)" 상위 몇 건. 네가 오판 잡게.
   - 마지막: `보기: http://localhost:8787`

## 규칙
- 한국어, 군더더기 없이. memo.md 기존 항목은 안 건드림(append만).
- 버린 목록 꼭 보여줘 — 필터 품질 검수용.

## Args
$ARGUMENTS
