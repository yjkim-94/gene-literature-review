# gene-literature-review — 프로젝트 지침

프로젝트 지침의 원본은 이 파일이다. `CLAUDE.md`는 `@AGENTS.md`로 이 파일을 import하므로 Claude Code와 Codex/agent가 같은 지침을 읽는다 — 지침은 여기만 고친다.

## 개발 후 마무리 루틴 (필수)

이 repo에서 **코드·동작·스킬 로직을 바꾼 뒤에는** 지시가 없어도 항상 아래 4단계를 순서대로 수행한다.
(단순 질의응답·조사처럼 파일을 바꾸지 않은 경우엔 적용하지 않는다.)

### 1. 문서 최신화
바뀐 내용을 관련 문서에 반영한다. 대상은 변경 성격에 따라 취사:
- `SKILL.md` — 스킬 워크플로우의 source of truth. 커맨드·인자·phase 동작이 바뀌면 반드시.
- `README.md` — 스크립트 한 줄 설명·검증 목록.
- `DESIGN.md` — **설계 결정**이면 `## Design <letter> — <제목> (YYYY-MM-DD)` 항목 신설(배경·before/after·검증).
- `dev_state.md` — §2 아키텍처 / §5 완료·남은 작업 / 헤더의 `최종 갱신` 날짜.
- 비자명한 로직(분기·loop·parser·네트워크)을 추가했으면 **offline 회귀 테스트**(`scripts/test_*.py`, 네트워크는 mock)도 같이 추가하고 통과 확인.

### 2. 커밋·푸시
이번 작업에서 바꾼 파일만 `git add <파일>`로 staging → 커밋 → **원격 push까지**. (`git add -A` 금지 — 다른 작업의 미커밋 변경이 섞인다.) (이 repo에서 "커밋"은 항상 push 포함.)
커밋 메시지 끝에 **이번 작업을 실제로 한 모델** 이름으로 `Co-Authored-By: <모델 이름> <noreply@anthropic.com>`(예: `Claude Opus 5.5`). 모델 이름을 이 파일에 고정하지 않는다 — 모델이 바뀌면 낡는다.

### 3. worknote 갱신
`worknote_YYMMDD.md`(오늘 날짜)를 기존 형식(목적·대상 데이터·작업 절차·주요 설정·출력 결과)으로 작성/갱신.
- worknote는 `.gitignore` 대상(**로컬 전용**) — 커밋하지 않는다.

### 4. install 동기화 (보통 자동 — 수동 불필요)
설치본(`~/.claude/skills/gene-literature-review/`)은 **SessionStart hook**
(`~/.claude/sync-codex-skills.ps1`)이 매 세션 시작마다 repo→install 미러링한다. Z: 마운트는 옛 내용을 줄 수 있어
mount를 robocopy하지 않고, innowl01의 repo 해시 목록(SSH)과 비교해 다른 파일만 scp로 받고 받은 뒤 해시를 확인한다.
제외: `output/`·`.git`·`__pycache__`·`.gt_cache`·`worknote_*.md`·`dev_state.md`·`pipeline_dev.html`. 설치본 최상위 `output/`(실행 결과)은 지우지 않는다.
서버의 working tree를 그대로 반영하므로 평소엔 수동 sync가 필요 없다.

**같은 세션 안에서 방금 바꾼 걸 즉시 설치본에 반영해야 할 때만** hook 스크립트를 직접 실행:

```powershell
powershell -NoProfile -File "$env:USERPROFILE\.claude\sync-codex-skills.ps1"
```
