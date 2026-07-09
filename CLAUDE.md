# gene-literature-review — 프로젝트 지침

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
`git add -A` → 커밋 → **원격 push까지**. (이 repo에서 "커밋"은 항상 push 포함.)
커밋 메시지 끝에 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

### 3. worknote 갱신
`worknote_YYMMDD.md`(오늘 날짜)를 기존 형식(목적·대상 데이터·작업 절차·주요 설정·출력 결과)으로 작성/갱신.
- worknote는 `.gitignore` 대상(**로컬 전용**) — 커밋하지 않는다.

### 4. install 동기화
worknote까지 쓴 뒤, repo를 설치본(`~/.claude/skills/gene-literature-review/`)에 미러링한다.
rsync가 없으므로 tar 오버레이 사용:

```bash
cd Z:/home/yjkim/dev/gene-literature-review && \
tar -c --exclude='./.git' --exclude='./output' --exclude='__pycache__' \
  --exclude='./.agents' --exclude='./.codex' --exclude='./.claude' \
  --exclude='./.gitignore' --exclude='./.gitattributes' \
  -f - . | tar -x -C ~/.claude/skills/gene-literature-review/
```

동기화 후 핵심 파일(`SKILL.md`, `scripts/*.py`) `diff`로 일치 확인.
