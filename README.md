# harness

Claude Code / Codex 양쪽에서 읽는 에이전트 작업 환경. 전부 평문 파일이고, 각 도구가 읽는 자리에 심링크로 연결된다.

```
skills/        SKILL.md 하나씩. Claude Code는 ~/.claude/skills/<name>, Codex는 ~/.codex/skills/<name>에 심링크
commands/      Claude Code 슬래시 커맨드 (Claude Code 전용). ~/.claude/commands → 이 폴더
principles/    원칙 하나에 파일 하나. 스킬이 절대경로로 참조한다
log.md         실패 로그. 한 줄씩
```

아직 없는 것(필요해질 때 만든다): 라우터, 레포별 `features/` 실험 맵, 검증 스크립트.

## 규칙 세 줄

모델이 읽는 자리: 2·3번은 `~/.claude/CLAUDE.md` Verification 섹션(세션마다 자동 로드), 1번은 각 SKILL.md의 Procedure discipline. 이 README는 사람용이다.

1. 플레이북 단계를 건너뛰면 `skip: <이유>`를 남긴다.
2. 판정 어휘는 고정. 작업: `PASS / ISSUES / BLOCKED`. 조사: `VERIFIED / NOT VERIFIED / INCONCLUSIVE`. Inconclusive는 pass가 아니다.
3. 모든 주장에 `measured / inferred / guess` 중 하나를 붙인다.

## 운영

- 모든 스킬 보고서의 첫 줄은 `판정: PASS | ISSUES | BLOCKED`. 판정자/critic은 실행 없이 확정하지 않는다(`measured` / `inferred` 표시).

- 에이전트가 틀리면 `log.md`에 한 줄.
- 같은 줄이 두 번 쌓이면 파일(스킬/원칙) 또는 스크립트로 올린다.
- 규칙마다 "이게 없으면 실제로 실패했다"는 근거가 `log.md`에 있어야 한다. 근거 없는 규칙은 지운다.
- 모델이 좋아져서 안 틀리게 된 규칙도 지운다.

## 어느 도구에서 되는가

| 항목 | Claude Code | Codex |
|---|---|---|
| hillclimb, investigate | O | O |
| code-review, plan-review | O (Agent 도구로 서브에이전트 사용) | X |
| report | O (Artifact 도구 사용) | X |
| commands/* (mm, slack-dm, weekly-report 등 6개) | O | X |

## pstack에서 가져온 것

출처: [pstack](https://github.com/poteto/pstack) v0.15.32, Lauren Tan, MIT. 가져온 파일은 각 파일 끝에 표기.

| 가져옴 | 원본 | 바꾼 것 |
|---|---|---|
| `skills/hillclimb` | playbook `hillclimb` | Cursor 서브에이전트/모델 라우팅, worktree, PR 단계 제거. step 1에 선행 연구 확인 추가(autore 사건 2건) |
| `skills/investigate` | playbook `investigation` + skill `figure-it-out` | how/why/unslop 라우팅 제거. 출력 형식과 판정 어휘만 유지 |
| `principles/` 4개 | `principle-prove-it-works`, `explain-the-number`, `attack-the-premise`, `encode-lessons-in-structure` | 축약. 관련 스킬 링크 제거 |
| 규칙 세 줄 | `poteto-mode` 라우터, `swarm`, `figure-it-out` | 909줄 라우터 대신 README 세 줄. code-review/plan-review에도 적용(첫 줄 판정, skip 이유, 판정자 실행 의무) |
| `log.md` | `reflect` / `recall` 스킬의 목적 | 트랜스크립트 마이닝 대신 수동 한 줄 |

안 가져온 것: 라우터 본문, 나머지 21개 플레이북, 나머지 20개 원칙, 스크립트 7천 줄, benny 자동화, `disable-model-invocation`.
