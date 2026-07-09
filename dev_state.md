# gene-literature-review — 개발 상태 (dev_state)

> 목적: 이 프로젝트가 **무엇을·왜·어떻게** 만들어졌는지, 그리고 **무엇을 시도했다 접었는지**를 한 곳에 정리.
> 사람과 다른 에이전트가 맥락을 빠르게 잡는 용도. 최종 갱신: 2026-07-09 (Phase 3 fan-out 배치 튜닝 포함).
>
> 세부 근거 문서: `docs/cdrs-eval-findings.md`(CDRS 기각), `docs/mcp-eval-plan.md`(MCP 대체 평가).

---

## 1. 프로젝트 개요

Claude Code **skill**. 사용자가 생물학 keyword(질병·pathway·phenotype 등)를 주면
① 관련 gene 목록을 특이도 순으로 뽑고 → ② 각 gene의 PubMed 문헌을 수집 → ③ gene별 요약 →
④ 통합 문서까지 만든다. 이미 gene 목록이 있으면 ②부터.

핵심 설계 철학(`DESIGN.md`): **list-centric**. gene 목록의 정확도가 제품이고, 문헌 요약은 그 목록이
맞다는 증거층이다. 그래서 "gene을 어떤 근거로 어떻게 순위 매기는가"가 이 프로젝트의 심장이다.

---

## 2. 현재 아키텍처

파이프라인(스크립트별 단일 책임):

```
scripts/fetch_genes.py     Phase 1 — keyword → 특이도 순 ranked gene 목록 (이 repo의 핵심);
                           옵션 --ot-overlay로 OpenTargets genetic/clinical 점수 컬럼(표시용)
scripts/opentargets.py     OpenTargets GraphQL 헬퍼 (keyword→EFO 해석 + target datatype 점수); --ot-overlay가 사용
scripts/fetch_pubmed.py    Phase 2 — gene별 PubMed abstract 수집 (lit/<SYMBOL>.json); PMID 선별은 PubTator entity 검색(--entity, Phase 1과 동일 쿼리), 없으면 free-text esearch fallback; abstract 본문·access·retraction은 efetch가 채움; PMID url·확인 gate 포함
scripts/verify_citations.py Phase 4 — 인용 PMID가 per-gene 파일에 실존하는지 기계 대조 (AI 아님, exit code)
scripts/runlog.py          공용 로깅 (per-phase A+B 로그, tail -f 가능)
scripts/test_*.py          fetch_genes·fetch_pubmed·verify_citations offline 회귀 테스트

evals/run_eval.py          curated gold(evals.json) recall 스모크 (네트워크 경량)
evals/ground_truth.py      OpenTargets gold 로더 (genetic_association·clinical, .gt_cache/ 캐시)
evals/cdrs_bench.py        spec 계열 랭킹 vs OT genetic gold (CDRS 제거 후 spec-only로 축소. 파일명은 git 연속성상 유지)
evals/candidate_c_bench.py OT-genetic 랭킹 vs 문헌 spec_adj_artifact 랭킹, gold=OT clinical (MCP 평가 §3D 산출)
docs/cdrs-eval-findings.md, docs/mcp-eval-plan.md  두 평가의 최종 결론 문서 ★ 먼저 읽을 것
```

산출물은 `output/<slug>/`에 모임(gitignore). `<slug>` = keyword의 kebab-case(예: `atopic dermatitis`
→ `atopic-dermatitis`), `fetch_genes.py`가 한 번만 계산하고 downstream이 경로 지역성으로 상속.

### Phase 1 랭킹 방법 (현재 default)

PubTator3의 **entity 기반 co-occurrence**로 특이도를 잰다(문자열 tiab 매칭 아님 — 그래서 `CAT`이
"고양이"가 아니라 catalase gene으로 잡힘).

- `co_papers` = gene entity ∩ disease entity 동시출현 논문 수
- `gene_papers` = gene entity 전체 논문 수
- `specificity = co_papers / gene_papers`, ranking key는 그 **Wilson lower bound**(`spec_adj`) —
  3/3 같은 소표본 우연이 140/400 같은 진짜 core gene을 못 이기게 하한으로 눌러줌.
- filter: `min_co 5`, `min_specificity(=spec_adj) 0.05`, `min_gene_papers 10`.
- **2026-07-07 채택**: 정렬 키가 `spec_adj` → `artifact_weight × spec_adj`로 바뀜. Ig/TCR/HLA 같은
  **구조적 문헌 아티팩트 gene**(예: IGHE)을 0.5× 감점(제거 아님). `is_artifact()` 심볼 regex로 판정.
  → 아래 §4의 CDRS 평가에서 유일하게 살아남아 검증된 개선.
- **2026-07-07 CDRS 전면 제거**: 모든 지표에서 baseline `spec_adj`를 못 이겨(§4), `--rank cdrs`
  산출 코드(z_rel·breadth·hub_penalty·panel·T_emp·4-track)와 `panel_random`·`build_panel_random.py`·
  `tune_weights.py`를 삭제. `fetch_genes.py`는 순수 spec_adj + artifact 감점만 남음(-1179 lines).
  `evals/cdrs_bench.py`는 spec-only 랭킹 벤치로 축소해 회귀 가드로 유지. artifact regex만 생존.
- **2026-07-07 OT overlay(옵션)**: `--ot-overlay`로 `ot_genetic`·`ot_clinical`(OpenTargets 점수) 표시용
  컬럼 부착. **랭킹에는 절대 안 들어감**(정렬은 여전히 순수 spec_adj+artifact), 기본 off, 실패해도 빈칸으로
  넘어가 core run 불변. 질병 keyword만(비질병 입력·network 실패는 빈칸). "DB 근거지 문헌 아님"으로만 참고.
  → 근거: MCP 평가에서 OT가 대체는 아니나 문헌이 놓친 임상 타깃을 건지는 **보완축**임을 측정(§3D).

---

## 3. 개발 타임라인 (git log 기반)

### (A) 초기 스킬 + 랭킹 기반 확립 — 2026-07-03 ~ 07-06
- `c7b3a5e` 최초 스킬. 이후 entity 기반 resolution, run-dir 레이아웃, bounded scoring(`60558fb`).
- 실측 기반 소소한 하드닝: co≤total 보장으로 wilson_lower 복소수 크래시 방지(`b7d44f5`),
  scoring pool 5×로 확대(`1b419c3`), PubTator 3-worker 병렬화(`f798f66`), per-phase 로깅(`1396837`).
- 이 시점 랭킹 = 순수 `spec_adj`. **여기까지가 안정 베이스라인.**

### (B) CDRS 실험 → 기각 — 2026-07-06 ~ 07-07 (상세: `docs/cdrs-eval-findings.md`)
특이도 지표 하나가 **필터·정렬을 겸해서** 임상 hub gene(IL4/IL13 등)이 잘리는 결함을 보고, "여러 무관
질병 대비 이 질병에서 얼마나 튀나"(z_rel)로 정렬하는 **CDRS(Cross-Disease Relative Specificity)**를
`--rank cdrs` 뒤에 구현(B_random 30질병 패널·permutation-null·4-track). 프로덕션 투입 전 **문헌 독립
정답셋**(OpenTargets `genetic_association` ≥ 0.5, 순환 차단)으로 오프라인 벤치. **결과: 11질병에서 CDRS가
단순 `spec_adj`를 못 이김**(hub_penalty는 오히려 해로움). 유일 생존은 Ig/TCR/HLA **artifact 감점**
(`spec_adj_artifact`, 무손실). → CDRS 전면 제거, artifact regex만 default 채택.

### (C) 문헌조사 무결성 안전장치 — 2026-07-07 (`DESIGN.md` Design G)
AI 문헌조사 리스크 감사에서 "안전장치가 prompt 지시뿐이거나 아예 없는" 무결성 공백을 발견 → 코드/문서로
보강(`DESIGN.md` Design G). identity-hallucination·token 방어는 이미 견고했고, 남은 공백만 저비용으로 닫음:
- **①철회 필터**: `fetch_pubmed.py`가 `PublicationType D016441`(철회 논문; D016440 *공지*는 제외) 파싱
  → 논문별 `retracted` 필드. 요약에서 ⚠철회 표기·근거 제외.
- **②인용 기계 검증**: `verify_citations.py` 신규 — 최종 md의 각 gene 섹션이 인용한 PMID가 그 gene
  `lit/*.json`에 실존하는지 **문자 대조**(모델 없음 → 검증 자체가 hallucinate 불가), orphan 있으면 exit 1.
- **③access 라벨 정직화**: `full-text` = 무료 전문 *이용 가능*(요약은 abstract 기준)임을 문구로 명확화.
  read-depth 과장 제거(라벨이 뜻하던 "how far read"는 실제로 availability였음).
- **④co-occurrence caveat**: `spec_adj`는 "그 병 맥락에서 연구된 정도"(무관·부정 결과 포함)이지 인과·연관의
  증명이 아님을 명시 — ranked list는 abstract로 검증할 lead set. 최종 판단은 사람.
- **⑤확인 gate(fail-closed)**: Phase 1→2 사람 검토를 코드로 강제 — `genes.confirmed`(OK 포함) 없으면
  `fetch_pubmed.py`가 exit. default 상태가 "정지"라 미검토 자동 진행이 불가.
- **하이퍼링크**: 논문 레코드에 `url`, 최종 md의 PMID를 PubMed 클릭 링크 + gene별 "전체 보기" 링크.
- **실사용 관통 확인**(atopic dermatitis): gate 차단 exit 1, lit json `url`·`retracted` 존재,
  `verify_citations` orphan 0, 클릭 링크 정상 — 전 안전장치 실데이터 통과. (⚠철회 경로는 이 키워드에
  철회 논문이 없어 unit test로만 커버 — §5 남은작업 참조.)

---

### (D) 기성 MCP 대체 평가 — 2026-07-07 (`docs/mcp-eval-plan.md`)
fetch 계층(Phase 1·2)을 기성 MCP(PubMed/PubTator/BioMCP/OpenTargets)로 대체할지 측정으로 판정. **결론:
fetch 계층 대체는 전부 부적격, 현 스크립트 유지가 정답.**
- **G1(token 안전성)이 A·B를 즉시 탈락**: PubMed MCP·PubTator MCP는 초록·annotation을 inline 반환(파일/
  count 모드 없음). 유일 생존 후보 BioMCP도 설치·실측 → `article get`이 초록을 context로 반환(MCP=G1
  위반), CLI로 우회해도 `pmcid`·`retraction`·`publication_types` 필드가 없어 **access 라벨·철회 필터
  (Design G) 상실**(G3) = "덜 코드"가 아니라 "덜 정확". Candidate B는 정확 co/total count 미노출로도 탈락.
- **버그 발견**: `ground_truth.py`가 OT drug-evidence를 `known_drug` id로 파싱했으나 **실제 id는
  `clinical`** → 캐시가 전부 0이었음(§4-4 재현). 수정해 clinical gold 확보.
- **Candidate C(OpenTargets 랭킹)**: OT-genetic vs 문헌 spec_adj_artifact를 clinical gold로 비교 →
  head-to-head **wash**(4질병 mean, per-disease 뒤집힘 = CDRS 교훈 #2 재현). 단 complement 분석에서
  OT-genetic이 문헌이 놓친 임상 타깃(RA: CD40·TYK2·IL2RA 등)을 건짐 → **대체 아니라 선택적 2nd-opinion
  축**으로만 가치. baseline `run_eval` recall@20 = 0.92(재측정).
- 신규 산출: `evals/candidate_c_bench.py`(Codex 작성, Claude 감독·재검증), `ground_truth.py` clinical 패치,
  `docs/mcp-eval-plan.md` §7 결과 채움. 판정 근거는 그 파일 §5·§7-1~7-5.

### (E) OpenTargets overlay 채택 — 2026-07-07 (`scripts/opentargets.py`, `--ot-overlay`)
(D)에서 확인된 OT의 **보완축** 가치를 실제 기능으로 흡수. 대체가 아니라 **선택적 표시 컬럼**으로만:
- `fetch_genes.py --ot-overlay` → keyword를 EFO/MONDO로 해석(`opentargets.resolve_efo`) 후 target별
  `genetic_association`·`clinical` 점수를 `ot_genetic`·`ot_clinical` 컬럼에 부착. `annotate_ot()`는 랭킹
  완료 **후** 실행 → 정렬/필터에 영향 0.
- **안전장치**: 기본 off, 전체 try/except로 감싸 EFO 미매칭(비질병 keyword)·network 실패 시 경고+빈칸으로
  core run 불변. 해석된 EFO id+질병명을 로그로 남겨 gate에서 사람이 감사(§4-4 교훈 적용).
- **framing**(SKILL.md 명시): "OT DB 근거지 문헌 아님" — `verify_citations`에 안 넣고, 논문으로 인용 안 하고,
  abstract 요약과 혼동 금지. 순수 참고 오버레이.

### (F) Recall eval 보강과 OT stress test — 2026-07-07 (`evals/run_eval.py`)
`run_eval.py`를 `recall@10/@30`, gold rank summary, miss 원인(`pool-miss`/`rank-cut`)까지 출력하도록 보강하고
결과를 `evals/output/recall_eval.md`에 저장하게 했다. `evals.json`은 `.gt_cache`의 OpenTargets
`genetic_association >= 0.5`가 30개 이상인 12 disease keyword만 남기고, 각 keyword 상위 30 genes로 고정했다.
실행 결과 mean `recall@30 = 0.13`으로 낮았고, miss는 대부분 `pool-miss`였다. 단, OT genetic gold는
문헌 co-occurrence specificity와 목표 함수가 달라 **main 성능 eval이 아니라 stress test/보완축 검증**으로만 해석한다.

## 4. 시행착오 & 교훈 (핵심 — 다음 에이전트가 반복하지 말 것)

1. **"정교한 방법 > 단순 baseline"은 착각이었다.** CDRS는 panel·z_rel·permutation-null·4-track까지
   갖춘 큰 설계였지만, 11질병 평가에서 **단순 `spec_adj`(Wilson lower bound)를 못 이겼다.** 프로덕션에
   남은 건 심볼 regex 한 줄(artifact 감점)뿐. → 방법을 키우기 전에 **정답셋 하니스부터** 만들었어야 했다.
2. **단일 케이스(AD) 검증 = confirmation bias.** AD에서만 돌려 IL4/IL13/IGHE가 "좋아 보였고" 채택
   직전까지 갔다. asthma/psoriasis로 넓히자 즉시 뒤집혔다. `method_dev` §4가 정확히 이걸 경고했는데도
   재현됨. → **다질병 held-out 없이 "더 낫다" 금지.**
3. **평가 정답셋의 순환논리.** 문헌 co-mention으로 랭킹하는 걸 문헌 유래 정답셋으로 평가하면 무의미.
   OpenTargets **genetic**(유전학 근거)로 끊었다. DisGeNET는 유료화(2026 기준)로 접근 불가 → 무료
   대체 탐색했으나 curated 채널이 sparse(AD 2개)해서 OT genetic 단일로 감.
4. **외부 DB 자동 매핑은 조용히 틀린다.** panel 생성 때 PubTator autocomplete top-hit가 "hepatitis C"
   를 엉뚱하게 Drug-Induced Liver Injury로 매핑. → keyword와 **word-set 일치 + 최대 count** 규칙으로
   canonical 개념 선택(`build_panel_random.py`). 결과 파일에 `name` 컬럼을 남겨 눈으로 감사 가능하게.
5. **캐시를 끝에만 저장하면 transient 실패에 다 날린다.** PubTator가 panel 스코어링(gene 37 × 질병 30
   ≈ 1,100 호출) 중 한 번 죽으면 `_get`이 6회 재시도 후 SystemExit → 전체 run 사망, 진행분 소실.
   → gene 단위 **incremental 캐시 저장 + `threading.Lock` + `try/finally`**(`ff3b6ea`). 재실행이
   캐시에서 재개.
6. **stale 산출물 재사용 버그.** 하니스가 기존 `genes_all_scored.tsv`를 헤더 확인 없이 재사용해서,
   이전 spec-mode dump(CDRS 컬럼 없음)를 그대로 써 모든 CDRS metric이 0으로 나옴. → 헤더에 `z_rel`
   있을 때만 재사용하도록 가드(`ff3b6ea`). **파일럿을 실제로 돌려서** 잡은 버그(단위테스트론 못 잡음).
7. **placeholder 상수를 "임의"라 폐기해놓고 또 도입하는 실수.** 0.05 컷을 "근거 없다"고 깠는데 CDRS의
   `bar_b=0.02`, weights `0.60/0.25/0.15`이 같은 죄. 코드에 `PLACEHOLDER` 라벨로 명시하고 결과에
   "미검증" 꼬리표를 붙여 과대포장을 막음. (weight sweep 결과: 튜닝해도 spec_adj를 못 이김.)
8. **PubTator 동시성 한계는 3 worker.** 8+ 던지면 429 폭주. `MAX_WORKERS=3` 고정. 벤치 돌 때 다른
   PubTator 작업을 병렬로 돌리면 rate limit 경합 → 하나씩.
9. **Windows/Z: 드라이브 + Codex.** Codex 샌드박스가 Z:(RaiDrive)를 못 봄 → `--sandbox
   danger-full-access`로 직접 실행하거나 C: 로컬 클론에서 작업. (이 프로젝트 후반 구현은 Codex가
   담당하고 Claude가 감독·검증·통합하는 방식으로 진행.)
10. **prompt 지시만으로는 안전장치가 아니다.** Phase 3 인용 규율이 "파일의 PMID만 인용하라"는 프롬프트
    문장뿐이었고 사후 검증이 없었다. 검증을 **코드로**(문자 대조, 모델 없음) 내리자 "검산이 또 hallucinate
    하면?"이라는 사슬도 끊김 — 문자 비교엔 지어낼 여지가 없음(`verify_citations.py`). 마찬가지로 사람 검토
    gate도 지시가 아니라 fail-closed 코드로 강제. → **신뢰의 근거는 지시가 아니라 기계적 확인.**
11. **OT genetic은 단독 main eval gold로 부적격하다.** 이 스킬의 Phase 1은 "문헌에서 keyword 맥락으로
    특이적으로 연구된 gene"을 찾고, OT genetic은 "variant/GWAS 기반 disease association"을 본다. 둘은
    독립 축이라 낮은 recall은 의미 있지만, "스킬 성능이 낮다"의 직접 증거는 아니다. → OT는 stress test,
    main eval은 GO/Reactome/MSigDB/curated review 같은 task-aligned gold가 필요.

---

## 5. 현재 상태 & 남은 것

**동작 상태**: Phase 1 랭킹 = `spec_adj` + artifact 감점(default). 옵션 `--ot-overlay`로 OT 표시 컬럼
(랭킹 불변). CDRS 코드는 전부 제거됨. 평가 하니스 = `run_eval.py`(recall@10/@30 + miss 원인 출력;
현재 OT stress test mean recall@30 0.13) + `cdrs_bench.py`(spec 랭킹 회귀) + `candidate_c_bench.py`(OT vs 문헌).

**검증 이력(2026-07-07, 요약 — 상세는 git log·테스트 가드)**:
- Phase 2~4 end-to-end 최초 관통(atopic dermatitis): 인용 무결성·교차오염 0 확인. 이 과정에서 실 PubMed
  XML로만 드러난 버그 2건 수정 → 둘 다 `test_fetch_pubmed.py`가 가드:
  ① inline 마크업 초록 유실(`t.text`→`itertext()`), ② pmcid가 reference 것으로 오염(ArticleIdList 직속경로).
- 도메인 일반성: 비면역(Parkinson) 재실행에서 교과서적 PD gene을 immune 오염 없이 랭킹. Phase 3~4를 Codex
  독립 실행 → Claude 무결성 검증 통과 → 템플릿이 도메인/작성자 비의존임을 입증.
- held-out `breast cancer`: `spec_adj_artifact` == `spec_adj`(Ig 오염 없어 감점 미발동) → 무손실 재확인.
- OT genetic stress test: `.gt_cache` 기반 12 disease × 30 gold genes로 `run_eval.py` 실행. 낮은 recall의 주원인은
  `pool-miss`였고, 이는 문헌 co-occurrence discovery와 genetic gold의 축 차이를 드러내는 보조 지표로 기록.
- Task-aligned GO-BP eval 초안: QuickGO 기반 5 keyword × 30 gold genes, scan 500. mean recall@30 0.14,
  miss 대부분은 여전히 `pool-miss` → ranking보다 candidate discovery/scan 단계가 병목.

**남은 작업**:
- [x] ~~Phase 2 문자열 검색 잔재~~ **entity 검색으로 전환 (2026-07-09, DESIGN.md §H)**. `fetch_pubmed.py`
      PMID 선별이 free-text esearch → PubTator entity(`"@GENE_<id>" AND "<entity>"`, Phase 1과 동일)로 바뀜.
      entity/`gene_id` 없으면(Mode B·novel term) free-text fallback 유지. abstract 본문·access·retraction은
      여전히 efetch. FLG·CAT 라이브 검증 통과(CAT의 "cat allergy" 1편은 PubTator NER 실태그 확인, 문자열 오염 아님).
      offline 회귀 테스트도 추가(`test_fetch_pubmed.py`: score 정렬·paging·malformed→empty를 `_get` mock으로 가드).
- [x] ~~fan-out 배치 크기 임의(~10)~~ **실측 튜닝 완료 (2026-07-09, DESIGN.md §I)**. batch≤30 / `agents=⌈N/30⌉` /
      동시 8(초과 wave)로 교체. 근거: 에이전트당 토큰 ≈ `38,800 + 4,950·b`(고정비 지배) → 적은/큰 에이전트가 유리,
      coverage 45까지 100%, 유일 결함은 co-presence 교차오염(부하 아님, verify_citations가 잡음).
- [ ] 인용은 `verify_citations.py`로 기계 가드(§3C②)되나, 요약 prose 품질 실검증은 여전히 LLM 실행 의존.
- [ ] ⚠철회 경로는 unit test(D016441)로만 커버 — 철회 논문이 실제 포함되는 키워드로 end-to-end 실검증 미완.
- [ ] OT overlay: **held-out 8질병(면역 밖 암·신경·대사·호흡 포함) 실검증 완료** — Measurement A는 여전히
      wash(대체 아님), **Measurement B 상보성은 7/8 질병에서 재현**(breast cancer CHEK2/KRAS/PIK3CA,
      melanoma CDK4/PARP1, IBD JAK2/TYK2/ITGA4 등; lupus만 empty). 면역 특유 아님 확정 → 표시 UX 착수 근거
      확보. **헬퍼 구현·검증 완료**(`scripts/ot_complement.py` genetic-forward 복제 선정 + `fetch_genes --ot-overlay`가
      `ot_scores.tsv` 덤프). 남은 건 SKILL.md Phase 4 템플릿 통합(노출 A 요약컬럼 + 노출 B 콜아웃) + 실 overlay
      run e2e. 상세 `docs/ot-overlay-ux-spec.md`.
- [x] ~~task-aligned main recall eval~~ **폐기 (2026-07-08)**. GO-BP(QuickGO) recall@30 0.14는 gold-tool
      construct MISMATCH를 잰 것 — pathway membership ≠ literature prominence라, gold를 늘려도 안 오름.
      OT literature score도 co-occurrence 기반이라 tautology. codex 2-agent 3라운드 토론 결론: 어떤 gold든
      그 숫자를 "recall"로 부르면 안 됨(서로 다른 construct). 결정: **recall eval 자체를 폐기**. 필요 시엔
      genetic-support overlap(GWAS Catalog `findByDiseaseTrait` 또는 기존 OT genetic, 무료·스크립트)을 "recall"이
      아니라 "literature-genetics gap" 지표로만 별도 report — 하지만 현재 착수 안 함.
- [ ] 역방향(스킬을 MCP server로 노출) 설계는 `docs/mcp-server-design.md`에 보류 문서로만 — 1인
      사용이라 착수 안 함. 외부 수요 생기면 그 문서의 3-도구(rank_genes/fetch_literature/verify_citations)로 착수.

## e2e 완료 (2026-07-08)

**OT overlay UX 실사용 e2e 통과** — Parkinson disease·systemic lupus erythematosus 2질병 전 구간
(Phase 1 발굴+overlay → 확인 gate → Phase 2 수집 → Phase 3 subagent 요약 → Phase 4 조립+OT 콜아웃+verify).
결과: 각 20 gene, verify_citations orphan 0, OT 콜아웃 15행씩 렌더(Parkinson BST1·PACRG·NR4A2 등 PD GWAS
loci, lupus TREX1·IRF5·TNFAIP3·TLR7 등 SLE GWAS — 문헌 top-20이 놓친 유전 위험 타깃). **주의**: 콜아웃 게이팅
(빈 결과→섹션 생략)은 이 2질병에선 안 걸림(둘 다 풍부) — 그 경로는 selftest로만 커버. e2e 중 잡은 fix 2건:
① `ot_complement.py` ENSG-only(심볼 없는 Ensembl id) 필터, ② SKILL 템플릿 `?term=PMID+PMID+` → 숫자-only 문구
(subagent가 리터럴 PMID를 URL에 넣던 버그). 산출 문서는 `output/<slug>/gene_literature_review.md`(gitignore).

## (이전 RESUME — 참고)

**OT overlay UX 기능 = 코드 완료·검증됨(미커밋, 디스크에 있음).** 변경: `scripts/ot_complement.py`(신규),
`scripts/fetch_genes.py`(ot_scores.tsv 덤프), `SKILL.md`(always-on overlay + Phase 4 노출 A/B + Two entry
modes), `evals/candidate_c_bench.py`(caveat 문구 fix), `docs/ot-overlay-ux-spec.md`·`docs/mcp-server-design.md`
(신규), `pipeline_dev.html`(신규, 스크립트 오케스트레이션 그래프 시각화). 오프라인 회귀·selftest 전 통과.

**진행 중인 e2e(실사용 검증) — Parkinson + lupus 2질병:**
- Phase 1·2 완료(`output/parkinson-disease/`, `output/systemic-lupus-erythematosus/` — gitignore).
  genes.tsv(각 20 gene, OT 컬럼 채워짐)·ot_scores.tsv·lit/*.json(각 98/100편)·genes.confirmed=OK 존재.
- Phase 3 진행: subagent 4개가 `output/<slug>/summaries_b1.md`·`summaries_b2.md`를 쓰는 중(멈춰도 파일 잔존).
- **남은 Phase 4(재개 지점)**: 각 질병마다 ① `summaries_b1+b2.md` 병합해 `gene_literature_review.md` 조립
  (헤더 + 요약 테이블[OT유전·OT임상 컬럼 포함] + `## OpenTargets 교차참조` 콜아웃 + 방법), ② 콜아웃은
  `python scripts/ot_complement.py --ot-scores output/<slug>/ot_scores.tsv --final output/<slug>/genes.tsv`
  출력 렌더(Parkinson=생성 예상, lupus=held-out에서 ot_only empty였으니 게이팅으로 섹션 생략되는지 확인),
  ③ `python scripts/verify_citations.py --review output/<slug>/gene_literature_review.md`로 orphan 0 확인.
- e2e 통과 후: repo → user skill(`~/.claude/skills/gene-literature-review/`) 동기화 + 커밋(원격 push).

**다음 에이전트가 먼저 읽을 것**: `docs/cdrs-eval-findings.md`(왜 CDRS를 접었는가), 이 파일, 그리고
Phase 1 랭킹을 건드린다면 `scripts/test_fetch_genes.py`(회귀 가드).
