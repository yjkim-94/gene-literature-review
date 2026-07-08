# 기성 MCP 대체 평가 계획 (mcp-eval-plan)

> **목적**: 기성 MCP(BioMCP / PubTator MCP / PubMed MCP / OpenTargets MCP)가 이 스킬의 특정 계층을
> 더 효율적·효과적으로 대체할 수 있는지 **측정으로 판정**하고, 나은 건 채택하거나 자체 구현으로 흡수,
> 아닌 건 폐기한다.
>
> **상태**: **실행 완료 (2026-07-07)**. 결론 = fetch 계층 MCP 대체 전부 부적격(§7·§9), OpenTargets는
> 보완축으로만. 결과는 §7-1~7-5, 판정은 §5 rubric·§9 최종 결론 참조. (계획 작성 시 HEAD `2742889`)
>
> **다음 세션 시작점**: 이 파일 → `dev_state.md` §3(E) → `DESIGN.md` Design G → `docs/cdrs-eval-findings.md`
> (순환논리·confirmation-bias 교훈) 순으로 읽고, 아래 §6 셋업 → §4 후보별 프로토콜 → §9 체크리스트로 진행.

---

## 0. 배경 (웹 조사 결과, 2026-07-07)

이 스킬의 **저수준 데이터 접근 계층은 이미 상품화**돼 있다:

| 기능 | 기성 MCP |
|---|---|
| NCBI E-utilities (esearch/efetch/esummary) = Phase 2 | PubMed MCP (`cyanheads/pubmed-mcp-server`, `Augmented-Nature/PubMed-MCP-Server`) |
| PubTator3 entity resolve·search·biocjson annotation = Phase 1 코어 | PubTator MCP (`JackKuo666/PubTator-MCP-Server`, `BioMCP-Hub`) |
| gene-disease 연관(점수) = Phase 1 대안 | OpenTargets MCP (`Augmented-Nature/OpenTargets-MCP-Server`), DisGeNET |
| 위 전부 통합 + 논문↔gene pivot + co-occurrence | **BioMCP** (`genomoncology/biomcp`) |

**대체 안 함(= 스킬의 부가가치)**: entity 기반 co-occurrence **specificity 랭킹**(Wilson lower bound +
artifact 감점 + floor)과 **integrity/orchestration 계층**(verify_citations · retraction · 확인 gate ·
파일 우회 token-safety · subagent fan-out). 이건 기성 MCP에 없다.

---

## 1. 절대 지켜야 할 불변식 (어떤 교체든 이걸 깨면 즉시 탈락)

교체 후보를 accept하기 위한 **하한선**. 효율이 좋아도 이걸 깨면 폐기.

- **G1 · Token 안전성 (가장 유력한 blocker)**: abstract/annotation 원문이 main context에 올라오면 안 됨
  (스킬의 핵심 = 파일 우회). MCP tool 결과는 **호출 agent의 context로 반환되는 게 기본** → bulk 데이터
  (초록 25편, biocjson 300편)를 MCP로 당기면 token blow-up이 되살아난다. → 서버가 **파일 저장 / 메타데이터-only
  / count-only** 모드를 지원하는지 반드시 확인. 없으면 그 서버는 Phase 2/scan 대체 부적격.
- **G2 · No generative gene identity**: gene 이름은 색인/DB에서만 나와야 함. MCP가 LLM 추론으로 gene을
  만들면 탈락(현 스킬의 단일 invariant).
- **G3 · 버그픽스 parity**: 현 스크립트가 실측으로 잡은 4개를 MCP 산출이 보장하는지 대조 —
  ① inline-markup abstract 보존(itertext), ② pmcid는 `ArticleIdList` 직속 경로(reference PMC 오염 없음),
  ③ retraction = `PublicationType D016441`(D016440 공지 제외), ④ co/total 동일 `@GENE` basis(quoting 대칭).
- **G4 · 결정성·재현성**: 정확한 `count` 필드 노출, run-dir 산출물, offline 회귀 테스트 가능성.
- **G5 · 평가 gold 독립성**: OpenTargets 소스로 랭킹하면 OT-genetic gold로 평가 금지(순환) — CDRS 교훈.
  OT 기반 후보는 **curated `evals.json` recall**로만 평가하거나 별도 독립 gold 필요.

---

## 2. 측정 인프라 (이 계획의 레버리지 — 이미 존재)

기존 하니스를 그대로 재사용해 후보를 **같은 gold·같은 metric**으로 잰다.

- **recall@20**: `python evals/run_eval.py` — `evals/evals.json`의 curated gold 대비 top-20 recall.
  후보가 ranked 심볼 리스트를 내면 `run_one()`의 산출부만 후보 호출로 갈아끼우면 됨.
- **랭킹 품질**: `evals/cdrs_bench.py`의 순수 함수 `precision_at_k` / `ndcg_at_k` / `auprc` 재사용
  (import해서 후보 ranked list + gold 넣기). gold·config는 `evals/bench_diseases.json`(tuning) +
  `bench_diseases_heldout.json`(held-out), OpenTargets gold는 `evals/ground_truth.py`(`.gt_cache/`).
- **공정 비교 원칙**: 동일 keyword set, 동일 gold, 동일 top-N, 동일 조직(human). tuning에서 방향 잡고
  **held-out으로 확정**(단일 케이스 confirmation-bias 금지 — CDRS 교훈 §4-2).

측정 축:
- **effectiveness**: recall@20, P@10/P@20/nDCG@20/AUPRC.
- **efficiency**: phase별 wall-clock, #API/tool calls, **context token 소비(G1)**, 코드 LOC·유지보수 표면
  (retry·rate-limit·XML 파싱을 얼마나 걷어내나).

---

## 3. 대체 후보 (우선순위 = 위험 낮고 이득 큰 순 아님, 이득 큰 순)

| # | 대상 계층 | 후보 MCP | 기대 이득 | 최대 리스크 |
|---|-----------|----------|-----------|-------------|
| A | Phase 2 abstract 수집 (`fetch_pubmed.py`) | PubMed MCP / BioMCP article | XML 파싱·retry·rate-limit 유지보수 제거 | **G1**(초록이 context로), **G3**(pmcid/inline/retraction parity) |
| B | Phase 1 PubTator ops (`fetch_genes.py`) | PubTator MCP / BioMCP | entity resolve·count 쿼리 위임 | **G1**(biocjson 300편), 정확 `count`·quoted-entity AND 노출 여부 |
| C | Phase 1 랭킹 대안 데이터소스 | OpenTargets / DisGeNET MCP | curated 근거로 recall↑ 가능성 | **G5 순환**, 제품 성격 변화(문헌근거→DB lookup), DisGeNET 유료 |
| D | entity 해석(query gate `--resolve`) | PubTator MCP autocomplete | 무 (현 코드가 이미 얇음) | 이득 거의 없음 — 빠르게 각하 예상 |

---

## 4. 후보별 실험 프로토콜 (가설 → 절차 → 판정)

각 후보는 **adopt(그대로 채택) / reimplement(더 나은 아이디어만 자체 흡수) / discard(폐기)** 중 하나로 판정.

### Candidate A — Phase 2 수집을 PubMed MCP / BioMCP로
- **가설**: E-utilities 래핑 MCP가 abstract+access+retraction+PMC 링크를 현 스크립트만큼 정확히,
  더 적은 유지보수로 준다.
- **절차**:
  1. G1 확인: 그 MCP가 초록 텍스트를 파일로 쓸 수 있나, 아니면 반드시 context로 반환하나? (README/도구 스펙)
     → context-only면 **여기서 discard**(핵심 설계 위반). 파일/스트리밍 지원 시 계속.
  2. G3 parity: 같은 5-gene(atopic dermatitis)로 MCP vs `fetch_pubmed.py` 산출 대조 —
     inline-markup 논문(PMID 34106037) 초록 보존?, pmcid가 reference 것으로 오염 안 됨?,
     retraction 논문이 있는 keyword(예: 알려진 철회 다수 분야)에서 D016441 표기 일치?
  3. 효율: 5-gene×5편 수집의 latency·호출 수·context token 대조.
- **판정**: G1·G3 모두 통과 + 효율 우위 → adopt(스크립트 얇게). 하나라도 실패 → 현 스크립트 유지, 좋은
  아이디어(있으면)만 흡수.

### Candidate B — Phase 1 PubTator ops를 PubTator MCP / BioMCP로
- **가설**: MCP가 entity resolve + `count`(co/total) 쿼리를 정확히 노출해 `fetch_genes.py`의 PubTator
  호출부를 대체할 수 있다.
- **절차**:
  1. G1 확인: scan 단계(300편 biocjson NER)를 서버가 **집계해서** 후보 gene 카운트만 주나, 아니면 raw
     annotation을 context로 쏟나? 후자면 scan 대체 부적격(scoring의 count 쿼리만 검토로 축소).
  2. `count` 정확성: MCP로 `"@GENE_2312" AND "@DISEASE_Dermatitis_Atopic"` co-count, `"@GENE_2312"`
     total-count를 뽑아 현 `_pubtator_count()`와 **수치 일치** 확인(G3-④ 동일 basis). 불일치면 specificity
     지표가 흔들리므로 그대로 못 씀.
  3. entity resolve만이라도 대체 가치 있나(Candidate D와 병합 판단).
- **판정**: count 수치가 스크립트와 일치하고 scan을 서버집계로 얻을 수 있으면 → 부분 adopt(PubTator I/O
  위임, 랭킹 로직은 유지). count가 어긋나거나 raw가 context로 오면 → discard(현 스크립트가 더 정밀).

### Candidate C — 랭킹 자체를 OpenTargets/DisGeNET association으로
- **가설**: 큐레이션된 gene-disease 점수가 문헌 co-occurrence 랭킹보다 recall/precision이 높다.
- **주의(G5)**: OT association으로 랭킹 → OT-genetic gold로 평가하면 순환. **curated `evals.json` recall**
  로 평가하거나, gold를 문헌·OT 양쪽과 독립인 제3소스로. DisGeNET는 2026 기준 유료(§cdrs-findings) —
  무료 접근 가능한지 먼저 확인, 안 되면 OpenTargets만.
- **절차**:
  1. bench keyword들에 대해 OpenTargets MCP로 disease→ranked targets(association score) 취득.
  2. `evals.json` curated gold로 recall@20, 그리고 **문헌 랭킹(spec_adj_artifact)과 교집합/차집합** 분석.
  3. 제품 성격 판단: OT는 "curated DB lookup"이라 **문헌근거 제시(PMID)라는 스킬 목적과 다름** → 대체가
     아니라 **보완 축**(2nd opinion / cross-check)으로 쓰는 게 맞는지.
- **판정**: recall이 명확히·다질병에서 우위면 → 랭킹 옵션으로 자체 흡수(단 gold 순환 배제 후). 아니면 →
  보완 축으로만(선택), 또는 discard.

### Candidate D — entity 해석을 MCP로 (빠른 각하 예상)
- 현 `--resolve`(PubTator autocomplete 직접 호출)는 이미 얇음. MCP로 감싸도 순 이득 없음 →
  **기본 discard**, Candidate B가 PubTator I/O를 통째로 가져갈 때만 딸려감.

---

## 5. 판정 rubric

각 후보를 표로:

| 후보 | G1 | G2 | G3 | G4 | G5 | effectiveness Δ | efficiency Δ | 결정 |
|------|----|----|----|----|----|-----------------|--------------|------|
| A | **fail** | pass | fail | pass | n/a | 미측정(게이트 탈락) | CLI시 −(무거움) | **discard** — MCP=abstract in-context, CLI=retraction/access 라벨 상실 |
| B | **fail** | pass | fail(count) | fail | n/a | 미측정(게이트 탈락) | = | **discard** — 정확 co/total count 미노출(PubTator MCP·BioMCP 공히) |
| C | n/a | pass | n/a | pass | wash(A) / 상보(B) | + (캐시 호출) | **reimplement** — 대체 아님(head-to-head wash), 선택적 2nd-opinion 축으로만 |
| D | n/a | pass | n/a | pass | n/a | 무 | 무 | **discard** — 이득 없음(B가 탈락이라 병합 대상도 소멸) |

- 불변식 칸: pass / fail / n/a. **하나라도 fail이면 adopt 불가**(reimplement/discard로).
- Δ: baseline(현 스크립트) 대비 +/-/=. effectiveness는 metric 수치, efficiency는 latency·token·LOC.
- 결정: adopt / reimplement / discard + 한 줄 근거.

---

## 6. 셋업 (다음 세션이 바로 실행)

> 정확한 설치 커맨드·도구 이름은 각 repo README로 확인(아래는 형태). Claude Code MCP 등록은 보통
> `claude mcp add <name> -- <run-cmd>` 또는 `.mcp.json`. **network 필요, danger-full-access/키 주의.**

- [ ] PubTator MCP: `git clone https://github.com/JackKuo666/PubTator-MCP-Server` → README대로 등록.
- [ ] PubMed MCP: `npx @cyanheads/pubmed-mcp-server` 계열 — `NCBI_API_KEY` 재사용.
- [ ] BioMCP: `genomoncology/biomcp` — `biomcp` CLI + MCP. DisGeNET 쓰려면 `DISGENET_API_KEY`(유료 확인).
- [ ] OpenTargets MCP: `Augmented-Nature/OpenTargets-MCP-Server`.
- [ ] 각 서버의 **"결과를 파일로 저장 가능한가 / count·metadata-only 모드"** 문서 확인 결과를 §7에 기록(G1 판정 선행).

측정 실행(기존 하니스, 그대로 동작 확인용):
```bash
python evals/run_eval.py                 # recall@20 baseline (현 스크립트)
python evals/cdrs_bench.py --selftest    # metric 함수 self-check
python evals/cdrs_bench.py               # baseline 랭킹 vs OT genetic gold
```
후보 평가는 이 두 하니스의 **입력(ranked list)만 후보 산출로 교체**해 같은 metric으로 비교.

---

## 7. 결과 기록 (채우기)

### 7-1. G1 문서 게이트 (2026-07-07, README/docs 조사 — 설치 前 판정)

각 서버 README·docs를 조사해 **"bulk 데이터(초록·annotation)를 호출 agent context로 반환하는가, 아니면
파일저장/count-only/metadata-only 모드가 있는가"**를 판정. §8의 prior(대부분 G1에서 갈림)가 확인됨.

| 후보 | 서버 | G1 판정 | 근거 |
|------|------|---------|------|
| A | PubMed MCP (`cyanheads/pubmed-mcp-server`) | **FAIL** | `pubmed_fetch_articles`가 abstract를, `pubmed_fetch_fulltext`가 전문을 **inline 반환**. 파일저장/count-only 모드 문서에 없음 → Phase 2 bulk 수집 대체 부적격(핵심 설계 위반). PMC 링크·pub-type은 있으나 **retraction(D016441) 언급 없음**(G3 부분 미달). |
| B | PubTator MCP (`JackKuo666/PubTator-MCP-Server`) | **FAIL** | 전 tool(`export_publications`·`batch_export_from_search`)이 annotation·biocjson을 **inline 반환**. **정확 co/total `count` 노출 없음** → G1 위반 + Candidate B의 핵심 요구(count 쿼리) 자체 미충족. |
| — | BioMCP (`genomoncology/biomcp`) | **PARTIAL → 실측 probe 필요** | counts-first 설계: CLI `--counts-only`, `search all` 집계, 데이터셋 `-o file` 출력, `get article <pmid> tldr`(요약). "output을 compact하게 유지" 명시. **단 MCP 인터페이스 레벨의 counts-only 지원·abstract-in-context 여부는 문서 불충분** → 설치 후 실측 필요. **유일한 G1 생존 후보**. |
| C | OpenTargets MCP (`Augmented-Nature/OpenTargets-MCP-Server`) | **n/a (소량 JSON)** | disease→ranked targets(size 1-500) 소량 메타데이터라 G1 무관. **★MCP 불필요**: `evals/ground_truth.py`가 이미 OT GraphQL `associatedTargets`(orderByScore `score`) + `datatypeScores.genetic_association`를 직접 쿼리·캐시(`.gt_cache/`). ranked list를 이 기존 쿼리로 재사용 가능 → MCP 래퍼는 순 오버헤드. |
| D | (entity resolve) | discard(예상대로) | 이득 없음. B가 PubTator I/O를 통째로 가져갈 때만 딸려감 — B가 FAIL이라 사실상 무의미. |

**게이트 결론**: standalone PubMed·PubTator MCP는 문서상 **inline bulk 반환 + 파일/count 탈출구 없음**으로
G1 확정 탈락(설치·probe 불요). Candidate C는 MCP가 기존 `ground_truth.py`와 중복 → MCP 설치 없이 평가.
**실제로 설치·probe할 가치가 있는 건 BioMCP 하나뿐**(counts-first 설계라 G1 통과 가능성 있는 유일 후보).

### 7-2. baseline 수치 (하니스 재확인)

| 지표 | 값 | 출처 |
|------|-----|------|
| `run_eval` mean recall@20 | **0.92** (ferroptosis 1.00, cuproptosis 1.00, autophagy 0.75) | `python evals/run_eval.py` (2026-07-07 재측정 — README의 0.83보다 높음) |
| `cdrs_bench` selftest | **pass** | metric·ranking·aggregation self-check |
| `cdrs_bench` spec_adj_artifact | _(미측정 — Candidate C 평가 시 함께)_ | `python evals/cdrs_bench.py` (OT genetic gold) |

### 7-3. BioMCP 실측 probe (2026-07-07, `biomcp-python` 0.7.3 설치·CLI 직접 호출)

문서 게이트에서 유일하게 살아남은 BioMCP를 실제 설치·호출해 확정. **결론: MCP 경로는 G1 FAIL,
CLI 경로는 G3 parity 상실 — fetch 계층 대체 후보로 부적격.**

- **`article search -g BRAF -d melanoma --json`** (3편): 2 KB. 필드 = title·journal·authors·date·doi·source·url.
  **abstract 없음**(metadata-only) → 검색 단계는 G1 친화적. 그러나 **top-level에 total count 없음**
  (`cbioportal_summary` + `articles[]`만) → **Candidate B(specificity용 co/total count) 충족 못 함**.
  CLI 0.7.3엔 문서가 말한 `search all --counts-only` 통합 명령이 없음(article-level count 미노출).
- **`article get 34106037 --json`**: 초록 원문 **inline 반환**(1401자). 필드 = pmid·date·journal·authors·
  title·abstract·full_text·pubmed_url.
  - **G3① PASS**: 이 PMID가 바로 우리 inline-markup 버그 케이스인데 초록이 "Introduction: Atopic
    dermatitis…"로 깨끗이 시작 → inline 마크업 정상(Europe PMC 소스).
  - **G3② / G3③ FAIL**: 반환에 `pmcid`·`publication_types`·`retraction` **필드 자체가 없음**,
    `full_text`도 빈 문자열 → **access 라벨(전문 가용성) · 철회 필터(D016441) 재현 불가**. Design G의 무결성
    기능이 소실됨.
  - **G1**: MCP로 호출하면 abstract가 context로 올라옴(bulk blow-up) → Phase 2 대체 부적격. CLI로 파일
    리다이렉트하면 G1은 피하나, 그 순간 biomcp는 `fetch_pubmed.py`보다 **무거운**(scipy·matplotlib·zarr·
    anndata·alphagenome 등 40+ 의존성) 대체 CLI일 뿐이고 위 G3 parity를 잃음 = "덜 코드"가 아니라 "덜 정확".

**Candidate A/B 종합 판정 (probe로 확정)**: Phase 2(A)·PubTator count(B) 모두 기성 MCP로 대체 시 G1
또는 G3에서 막힘 — §8의 prior가 실측으로 확정됨. fetch 계층은 현 스크립트 유지가 정답. 유일하게 살아있는
실험은 **Candidate C(OpenTargets 랭킹)**, 그리고 그건 MCP 없이 기존 `ground_truth.py` 쿼리로 평가 가능.

### 7-4. Candidate C 셋업 (2026-07-07) — gold = OT 임상 신약 타깃

사용자 결정: **gold = OT known-drug(임상) 타깃**(OT-genetic 랭킹과 준독립 → 순환 회피). "OT-genetic 랭킹 vs
문헌 spec_adj_artifact 랭킹, 어느 쪽이 임상 검증 타깃을 더 잘 회수하나".

- **버그 발견(§4-4 재현, FIXED 2026-07-07: now uses `clinical`)**: 당시 `ground_truth.py`가 `datatypeScores.id == "known_drug"`로 파싱했는데,
  **OT의 실제 datatype id는 `clinical`**(라이브 쿼리로 확인: AD top 타깃 datatypes = genetic_association·
  literature·genetic_literature·rna_expression·animal_model·**clinical**). → `known_drug` 매칭이 한 번도
  안 돼 `.gt_cache/` 전 질병 `known_drug={}`(0개)로 저장돼 있었음. **수정 완료 기록.**
- 수정 완료: `ground_truth.py`에 `clinical` datatype 파싱 추가 + gt 캐시 refresh. gold = `clinical` score
  ≥ threshold 타깃.
- 데이터 가용성: 4 tuning 질병 scored TSV는 `output/atopic-dermatitis`만 캐시됨 → asthma·RA·psoriasis는
  `fetch_genes` 재실행 필요(PubTator, 순차).
- 구현은 Codex 위임(신규 `evals/candidate_c_bench.py` + `ground_truth.py` 소패치), Claude가 spec·재검증.

### 7-5. Candidate C 측정 결과 (2026-07-07, 4 tuning 질병, clinical gold)

`python evals/candidate_c_bench.py --refresh-gt` → `evals/output/candidate_c_SUMMARY.md`.

**Measurement A (동일 candidate universe 랭킹 품질, mean across AD·asthma·RA·psoriasis):**

| ranking | P@10 | P@20 | nDCG@20 | AUPRC |
|---------|------|------|---------|-------|
| lit (spec_adj_artifact) | **0.550** | **0.425** | 0.532 | 0.489 |
| ot_genetic | 0.450 | 0.350 | **0.537** | **0.577** |

- **wash**. lit이 최상위 정밀도(P@10/P@20) 우위, ot_genetic이 순위품질(nDCG/AUPRC) 근소 우위(nDCG는
  0.537 vs 0.532 = noise 수준). **per-disease는 뒤집힘**: AD→lit 완승, asthma→ot 완승(AUPRC 0.842),
  RA·psoriasis→혼전. CDRS 교훈 #2(단일 케이스로 판단 금지) 패턴 재현 — 어느 쪽도 대체 우위 아님.
- gold-in-candidates가 질병당 11~22로 작음(clinical gold 총 125~350이나 candidate pool과 겹치는 건 소수).

**Measurement B (complement — OT-genetic top-20이 문헌 top-20이 놓친 clinical 타깃 `ot_only`):**

| 질병 | ot_only (문헌이 놓친 임상 타깃) |
|------|------|
| RA | **CD40, IL12B, IL2RA, TRAF3IP2, TYK2** |
| asthma | IL1RL1 |
| psoriasis | IL13 |
| AD | (없음) |

- co-occurrence 랭킹이 **구조적으로 under-rank하는 임상·유전 위험 타깃**을 OT-genetic이 건져올림
  (특히 RA의 CD40·TYK2·IL2RA — 실제 승인/임상 약물 타깃). 반대로 `lit_only`는 잘 알려진 cytokine
  (IL17A·IL5·TNF 등)으로 문헌이 강함. → 두 신호가 **상보적**.

**판정: reimplement(보완축) — 대체 아님.**
- **replace 기각**: 4질병 head-to-head가 wash이고 per-disease가 뒤집힘 → 문헌 랭킹을 OT로 갈아탈 근거
  없음. 게다가 OT로 갈면 제품이 "문헌근거(PMID) 제시"에서 "curated DB lookup"으로 성격이 바뀜(§4-C 주의).
- **complement 가치는 실재**: Measurement B가 문헌 co-occurrence의 사각지대(임상 타깃)를 OT-genetic이
  메운다는 구체 증거를 보임. → 선택적 **2nd-opinion 축**(genetic/clinical cross-check)으로 흡수할 가치.
  단 실제 feature화는 제품 결정 사항이며, 현 스킬 목적(문헌 lead set + 사람 최종판단, Design G ④)과
  정합적으로 "참고 오버레이"로만.
- **정직 caveat**: 4질병 전부 면역/염증(상관된 biology), held-out 아님, gold-in-candidates 소량 →
  directional. "OT가 낫다"가 아니라 "상보적"까지가 데이터가 지지하는 최대. held-out은 complement를 실제
  feature로 추진할 때만 필요(CDRS와 동일 규율).

---

## 8. 리스크 · 미해결

- **G1이 대부분을 결정할 가능성**: MCP는 tool 결과를 context로 주는 게 표준이라, bulk 데이터(초록·annotation)
  대체는 token 관점에서 오히려 손해일 공산이 큼. → 가장 유망한 실이득은 (a) entity resolve 같은 **소량 메타데이터**
  호출, (b) OpenTargets를 **보완 축**으로 붙이는 것일 수 있음. *가설이며, 측정으로 확정할 것.*
- **정밀 제어 상실 위험(G3)**: 현 스크립트의 quoting 대칭·pmcid 직속경로·retraction UI 매칭은 실측 버그픽스.
  MCP가 이를 재현 못 하면 "덜 코드"가 아니라 "덜 정확".
- **의존성·수명**: 3rd-party MCP는 유지보수·API 변경 리스크. self-host vs 원격.
- **평가 noise**: bench gold-in-candidates가 작음(4~11) → 방향성 판단이지 유의성 검정 아님(CDRS 교훈 재적용).

---

## 9. 진행 체크리스트 (resumable state)

- [x] §6 셋업: G1 문서 게이트(4개 전부) + BioMCP 설치·실측 probe → §7-1/7-3. **standalone PubMed·
      PubTator MCP는 문서상 G1 확정 탈락이라 등록 불요**; BioMCP만 설치·probe(→ 부적격 확정).
- [x] baseline `run_eval` mean recall@20 = **0.92** 고정 → §7-2. (`cdrs_bench` spec_adj_artifact는 C와 함께)
- [x] Candidate A: G1 fail(abstract in-context) + G3 fail(retraction/access 상실) → **discard** 확정.
- [x] Candidate B: 정확 co/total count 미노출(PubTator MCP·BioMCP 공통) → **discard** 확정.
- [x] Candidate C: OT-genetic 랭킹 vs 문헌 랭킹, gold=clinical(known-drug) → **reimplement(보완축) 판정**.
      head-to-head wash(§7-5 Measurement A), 상보성은 실재(Measurement B: RA CD40/TYK2/IL2RA 등).
- [x] Candidate D: 각하 확정(B 탈락으로 병합 대상 소멸).
- [x] §5 rubric 표 완성(A·B·D·C 전부).
- [x] `dev_state.md`에 결론 반영(§3 (F) 추가). **이 파일 상태: 실행 완료(2026-07-07).**

**최종 결론(2026-07-07)**: fetch 계층(Phase 1·2)의 기성 MCP 대체는 **전부 부적격** — G1(token 안전성) +
G3(retraction/access parity)가 A·B를 막고, BioMCP도 MCP=G1·CLI=G3에서 탈락. **현 스크립트 유지가 정답.**
유일한 실이득 후보였던 OpenTargets(C)는 문헌 랭킹의 **대체가 아니라 상보축**(임상 타깃 cross-check)으로만
가치 — 실제 feature화는 별도 제품결정. 즉 이 스킬의 부가가치(specificity 랭킹 + integrity 계층)는 기성
MCP로 대체 불가임이 측정으로 확정됨.

**원칙(CDRS에서 배운 것 재적용)**: ① 측정 하니스부터, 방법 키우기 전에. ② 단일 케이스로 "더 낫다" 금지 —
held-out까지. ③ gold 순환 배제. ④ placeholder/미검증은 "미검증"으로 표기, 과대포장 금지.
