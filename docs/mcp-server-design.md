# 스킬을 MCP server로 역노출 — 설계 노트 (mcp-server-design)

> **목적**: 이 스킬을 기성 MCP로 *대체*하는 게 아니라(→ `mcp-eval-plan.md`에서 전부 부적격 판정),
> 반대로 **이 스킬 자체를 MCP server로 노출**해 다른 agent가 도구로 부르게 하는 방향의 설계.
>
> **상태**: **보류 — 문서로만 (2026-07-08)**. 현재 사용자는 1인(자기 Claude Code에서만 사용) →
> MCP 껍데기값을 낼 외부 수요 없음. skill 형태 유지가 정답. **아래 조건이 생기면 이 설계로 착수.**
>
> **착수 트리거**: 사용자 외 다른 사람/다른 AI agent가 이 파이프라인을 도구로 호출할 실수요가 생길 때
> (예: 동료가 자기 Claude/Desktop에서 gene 랭킹을 쓰고 싶다). 그 전엔 만들지 말 것(YAGNI).

---

## 1. 왜 이 방향만 말이 되나

`mcp-eval-plan.md`는 "우리가 기성 MCP를 **쓰는**" 방향을 측정으로 전부 기각했다(G1 token 안전성 위반 —
초록·annotation을 context로 쏟음). 그 역, "우리가 **MCP가 되는**" 방향은 중복이 없다: 시중 PubMed/
PubTator/BioMCP MCP에 **없는 게 정확히 이 스킬의 부가가치**(specificity 랭킹 + verify_citations·retraction·
확인 gate 무결성 계층)이기 때문. 빈자리를 채우는 유일한 연계.

---

## 2. 절대 규칙 — "내용물이 아니라 위치표를 돌려준다"

MCP tool 결과는 호출 agent의 context로 반환되는 게 표준. 그래서 스킬을 MCP로 감싸도 **G1을 스킬 스스로
지켜야** 한다: 초록 원문은 **파일에 저장**하고, 반환은 **경로 + 소량 메타데이터(gene 목록·count·PMID·
플래그)뿐**. 도서관 사서가 책을 복사해 주는 게 아니라 청구기호만 적어주는 것과 같다. 이건 스킬이 원래
파일 우회로 하던 걸 MCP 껍데기에서도 강제하는 것.

---

## 3. 노출할 도구 (기존 스크립트 위 얇은 래퍼)

| 도구 | 입력 | 반환 (작은 것만) | 파일로 감추는 것 | 래핑 대상 |
|------|------|------------------|------------------|-----------|
| `rank_genes` | keyword | 특이도순 gene 목록(symbol, spec_adj, co/total) | 없음(원래 작음) | `fetch_genes.py` |
| `fetch_literature` | gene, keyword | **파일 경로** + 논문 수 + PMID 목록 + 철회 플래그 | 초록 원문 `lit/<gene>.json` | `fetch_pubmed.py` |
| `verify_citations` | 최종 문서 경로 | pass/fail + orphan PMID | 없음 | `verify_citations.py` |

- **핵심 불변식**: `fetch_literature`는 **절대 초록 텍스트를 반환하지 않는다**. 부르는 agent는 경로만
  받고 필요 시 자기가 파일을 읽는다. (G1 준수의 심장)
- **gate 유지(fail-closed)**: `rank_genes` 결과를 사람이 승인(`genes.confirmed`)하기 전엔
  `fetch_literature`가 거부. MCP로 노출해도 default가 "정지"여야 함.
- **무결성 계층이 공짜로 딸려감**: 철회 필터·인용 기계검증이 도구에 내장돼, 시중 MCP엔 없는 값어치가
  그대로 노출된다.

---

## 4. 착수 시 주의 (ponytail)

MCP server는 프로토콜 핸들러·도구 등록·배포 껍데기 코드가 붙는다. 이 값은 **"남이 꽂아 쓸 때"** 나온다.
1인 사용에선 skill이 더 싸다. 착수하더라도 §3의 3-도구를 **기존 스크립트 위 얇은 래퍼**로만 감쌀 것 —
랭킹·파싱·무결성 로직은 스크립트에 그대로 두고 MCP 레이어는 I/O 변환만. 새 로직을 MCP 레이어에 넣지 말 것.
