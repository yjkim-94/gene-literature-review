# gene-literature-review — 개발 상태 (dev_state)

> 목적: 이 프로젝트가 **무엇을·왜·어떻게** 만들어졌는지, 그리고 **무엇을 시도했다 접었는지**를 한 곳에 정리.
> 사람과 다른 에이전트가 맥락을 빠르게 잡는 용도. 최종 갱신: 2026-07-07 (HEAD `36d44a2`).

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
scripts/fetch_genes.py     Phase 1 — keyword → 특이도 순 ranked gene 목록 (이 repo의 핵심)
scripts/fetch_pubmed.py    Phase 2 — gene별 PubMed abstract 수집 (lit/<SYMBOL>.json)
scripts/test_fetch_pubmed.py         Phase 2 XML 파싱 offline 회귀 테스트
scripts/runlog.py          공용 로깅 (per-phase A+B 로그, tail -f 가능)
scripts/test_fetch_genes.py          Phase 1 offline 회귀 테스트

evals/cdrs_bench.py        정량 평가 하니스 — spec 계열 랭킹 vs OpenTargets genetic gold
                           (CDRS 제거 후 spec-only 전용으로 축소. 파일명은 git 연속성상 유지)
evals/run_eval.py          curated gold(evals.json) recall 스모크 (네트워크 경량)
docs/cdrs-eval-findings.md CDRS 평가 최종 결론 문서 ★ 먼저 읽을 것
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

---

## 3. 개발 타임라인 (git log 기반)

### (A) 초기 스킬 + 랭킹 기반 확립 — 2026-07-03 ~ 07-06
- `c7b3a5e` 최초 스킬. 이후 entity 기반 resolution, run-dir 레이아웃, bounded scoring(`60558fb`).
- 실측 기반 소소한 하드닝: co≤total 보장으로 wilson_lower 복소수 크래시 방지(`b7d44f5`),
  scoring pool 5×로 확대(`1b419c3`), PubTator 3-worker 병렬화(`f798f66`), per-phase 로깅(`1396837`).
- 이 시점 랭킹 = 순수 `spec_adj`. **여기까지가 안정 베이스라인.**

### (B) CDRS 실험 — "cross-disease 상대특이도"로 랭킹 고도화 시도 — 2026-07-06 ~ 07-07
동기(`method_dev.md`, test 폴더): 특이도 지표 하나가 **필터와 정렬을 겸해서** 임상 검증된 hub
gene(IL4/IL13 등, `gene_papers`가 큰)이 순위에서 밀려 잘리는 결함. → 필터와 정렬을 분리하고,
"여러 무관 질병 대비 이 질병에서 얼마나 튀는가"(z_rel)로 정렬하자는 **CDRS(Cross-Disease Relative
Specificity)** 방법론.

구현(전부 `--rank cdrs` 뒤, default는 spec 유지 = 하위호환):
- `f8d463b` **B_random 패널** 30질병(`panel_random.tsv`) — 6 category 균형, volume 층화, 벤치마크
  질병 제외(순환 방지).
- `9c268de` **observe 컬럼**: `z_rel`(robust z), `breadth_random`(hub 여부), `hub_penalty` + PubTator
  count 캐시. 랭킹은 안 바꾸고 컬럼만(관찰).
- `0896d22` **Stage 3**: `T_emp`(permutation-null threshold) + 4-track 라벨(established / related_
  pleiotropic / exploratory / artifact).

### (C) 정량 평가 하니스 — "CDRS가 진짜 더 나은가" 측정 — 2026-07-06 ~ 07-07
CDRS를 프로덕션에 넣기 전에 **외부·문헌 독립 정답셋**으로 검증(`method_dev` §7④, `b177972` spec).
- 정답셋 = **OpenTargets `genetic_association`** score ≥ 0.5 (유전학 근거 = 문헌 co-mention과 독립
  → 순환논리 차단). DisGeNET는 유료 전환으로 폐기, 무료 대체(DISEASES/Jensen)는 너무 sparse해 기각.
- 하니스(`evals/`): `fetch_genes --rank cdrs` 출력 컬럼에서 **6개 랭킹을 오프라인 재계산**해 gold와
  비교(P@10/P@20/nDCG@20/AUPRC). step 4(정렬 스위치) 없이도 평가 가능 = weight를 재실행 없이 튜닝.
- `9b12427` 하니스(AD 파일럿) → `2445801` 4질병 macro 요약 → `6ca6ca0` weight/toggle sweep.

### (D) 결론과 채택 — 2026-07-07
- `586a3d2` AD 단독은 CDRS 우세로 보였으나(confirmation bias), 4질병(AD·asthma·RA·psoriasis)
  평균에선 **현행 spec_adj가 CDRS를 이김**.
- `3b1b123` candidate pool 확대(scan 200/max 30, gold 겹침 7~11개)로 결론 강화: CDRS는 최하위권.
  단 `spec_adj_artifact`(artifact 감점만)는 spec_adj를 **일관되게 소폭 이김**.
- `09c9650` held-out 8질병 재확인: `spec_adj_artifact`는 held-out 전 질병에서 spec_adj와 **동일**
  (그 질병들엔 Ig gene 오염이 없어 감점이 발동 안 함) → **무손실 확정**.
- `36d44a2` **artifact 감점만 default에 채택.** CDRS 나머지(z_rel·hub_penalty·panel)는 폐기,
  `--rank cdrs` 실험 컬럼으로만 보존.

---

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

---

## 5. 현재 상태 & 남은 것

**동작 상태**: Phase 1 랭킹 = `spec_adj` + artifact 감점(default, 유일 모드). CDRS 코드는 전부 제거됨.
평가 하니스: `evals/cdrs_bench.py`(spec-only, held-out-8 config로 재현) + `evals/run_eval.py`(recall 스모크).

**정리 완료(2026-07-07)**:
- [x] held-out `breast cancer` 재실행 완료 — `spec_adj_artifact` == `spec_adj`(cancer엔 Ig 오염 없어
      감점 미발동) → 무손실 결론 재확인. 기록 채움.
- [x] CDRS 제거 완료(위 §2 참조). z_rel·T_emp·panel·`--rank cdrs`·`tune_weights.py` 삭제.
- [x] `run_eval.py` ↔ `cdrs_bench.py` 통합 판단: **통합 안 함**. gold source(curated vs OpenTargets
      genetic)도 목적(recall 스모크 vs 랭킹 벤치)도 달라 통합 이득 없음. 둘 다 유지.

**Phase 2 검증(2026-07-07)**:
- [x] `fetch_pubmed.py` 첫 end-to-end 실행 → **버그 발견·수정**: abstract/title을 `t.text`로 뽑아
      inline 마크업(`<i>`·`<sub>`·structured-abstract label)으로 시작하는 논문은 빈 문자열로 넘어감
      (PMID 34106037 실측). → `itertext()`로 수정, XML 파싱을 `parse_pubmed_xml()`로 분리 + offline
      회귀 테스트(`test_fetch_pubmed.py`). unit test로는 못 잡는 버그 — 실제 PubMed XML 필요.

**남은 작업**:
- [ ] Phase 3~4는 스크립트가 아니라 SKILL.md의 프롬프트/템플릿 지침(gene별 요약·통합 문서). 아직
      어떤 output에도 `lit/`·`gene_literature_review.md`가 없음 = **한 번도 end-to-end 실행 안 됨**.
      실제 키워드로 파이프라인을 끝까지 돌려야 요약 품질·PMID 인용·문서 형식이 검증됨.

**다음 에이전트가 먼저 읽을 것**: `docs/cdrs-eval-findings.md`(왜 CDRS를 접었는가), 이 파일, 그리고
Phase 1 랭킹을 건드린다면 `scripts/test_fetch_genes.py`(회귀 가드).
