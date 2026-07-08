# OT overlay 표시/활용 UX — 스펙 (ot-overlay-ux-spec)

> **목적**: `--ot-overlay`의 OpenTargets 점수를 최종 문서(`gene_literature_review.md`)에 **어떻게**
> 노출할지 확정. 지금까지 OT는 `genes.tsv` 컬럼(`ot_genetic`·`ot_clinical`)으로만 존재했고 최종 문서엔
> 안 나타났다(`dev_state.md` §5 남은작업).
>
> **상태**: **설계 확정, 착수 대기 (2026-07-08)**. 착수 전제 = held-out 다질병 eval(A)에서 상보성 재현.
> A 미통과 시 이 스펙 폐기(overlay는 tsv-only 유지). A = `candidate_c_bench.py --heldout`.
>
> **분담**: 노출 A(SKILL 템플릿) = Claude 저작. 노출 B 헬퍼(`scripts/ot_complement.py`) = Codex 구현·
> 자체검증, Claude 스펙·재검증. 렌더 지시(SKILL) = Claude.

---

## 0. 핵심 통찰 (스펙을 가르는 이유)

측정된 상보가치(`mcp-eval-plan.md` §7-5 Measurement B)는 **"문헌 top-N에 없는데 OT가 지목한 임상 타깃"**
(RA: CD40·TYK2·IL2RA 등)이다. 그런데 최종 문서는 **문헌 top-N만** 담는다. 따라서 OT 점수를 최종 문서의
gene(=문헌이 이미 고른 gene)에 붙이면 정작 측정가치(문헌이 놓친 타깃)는 안 보인다. → 노출을 두 갈래로 나눈다.

**★ 소스 결함 교정(2026-07-08, 재검증으로 발견)**: 상보 타깃의 상당수는 **pool-miss** — PubTator keyword
scan이 후보로조차 안 올려 `genes_all_scored.tsv`에 **없다**(실측: breast cancer CHEK2/KRAS/PIK3CA가 98개
scan pool에 부재). 따라서 복제 소스를 `genes_all_scored`로 잡으면 "scan은 됐지만 랭킹에서 밀린" gene만
건지고 pool-miss 헤드라인 타깃을 구조적으로 놓친다. → **복제 소스는 OpenTargets 전체 타깃 목록**이어야 하며,
그러려면 overlay가 그 목록을 파일로 남겨야 한다(§4-0).

---

## 1. 게이팅 (불변식 — 절대 준수)

- 노출은 **`--ot-overlay`가 실행됐고 OT 컬럼이 비어있지 않을 때만**.
- **기본 상태(overlay off)에서 최종 문서는 완전 불변** — 컬럼도 섹션도 추가되지 않는다. (core run 불변 원칙)
- OT 조회 실패·비질병 keyword로 컬럼이 전부 빈 경우도 노출 없음(현 overlay의 fail-soft와 동일).

---

## 2. 노출 A — 교차참조 컬럼 (문헌이 고른 gene에, 라이트)

- 최종 문서 **요약 테이블에 2컬럼 추가**: `OT유전` / `OT임상` = 점수(소수 3자리) 또는 `–`(OT 미보고).
- 의미: "이 문헌-선정 gene이 OT DB에서도 유전/임상 근거를 갖나" = **안심/맥락용**. (측정가치 아님)
- 혼동 방지: 요약 테이블 바로 위 또는 컬럼 헤더 각주에 **"OT유전·OT임상 = OpenTargets DB 점수(문헌 근거
  아님)"** 명시.
- 구현: SKILL.md Phase 4 템플릿 지시로만(모델이 `genes.tsv`의 두 컬럼을 읽어 렌더). 신규 코드 없음.

## 3. 노출 B — 상보 콜아웃 (측정가치의 핵심) ★

- 최종 문서에 **별도 섹션** `## OpenTargets 교차참조 (문헌 근거 아님)`:
  > OpenTargets DB는 이 문헌 상위 목록엔 없지만 유전/임상 근거가 강한 다음 타깃도 보고함:
  > **CD40**(임상 0.91), **TYK2**(유전 0.72), **IL2RA**(임상 0.85) … — 각 심볼은 DB 점수만, 문헌 미검증.
- 선정 규칙 = **OpenTargets 전체 타깃 목록**(`ot_scores.tsv`)에서 **(OT 점수 높음) ∧ (문헌 최종 top-N에
  없음)**. pool-miss 포함 → 이게 RA의 CD40/TYK2, breast cancer CHEK2/KRAS/PIK3CA를 건지는 자리 = 측정가치의 실현.
- **top-K bound**: 임계값을 넘는 타깃이 많으므로(1699개 중 다수) 상위 K개만(default 15) 노출.
- **genetic-forward 정렬(★ 실측 교정 2026-07-08)**: clinical 점수로 정렬하면 **약물-표적 gene family가 도배**됨
  (실측: breast cancer top-15이 taxane 표적 tubulin paralog TUBA/TUBB 14개 — 모두 clinical 0.996 동일).
  문헌 랭킹의 Ig/TCR artifact와 같은 family-flooding. genetic으로 정렬하면(tubulin genetic=0) 붕괴하고,
  측정가치(Measurement B는 genetic 축)와도 정합. → 정렬 = **genetic desc, clinical desc, symbol asc**. 그러면
  top-15 = CHEK2·BRIP1·MSH6·PIK3CA·MSH2·MLH1·RAD51C·ATM·KRAS·PTEN(유전 위험 유전자) — insightful.
- **결정성 필수**(lesson #10): LLM이 TSV를 눈으로 diff하면 안 됨 → **헬퍼 스크립트가 목록을 산출**,
  LLM은 출력만 렌더. 지어낼 여지 0.

---

## 4. 구현 스펙 (Codex 구현, Claude 재검증)

### 4-0. `fetch_genes.py --ot-overlay` — 전체 OT 목록 덤프 (신규)
- overlay가 `fetch_target_scores(efo)`로 받는 전체 OT 타깃 dict(현재 annotate 후 버려짐)를
  `output/<slug>/ot_scores.tsv`로 저장. 컬럼 `symbol, ot_genetic, ot_clinical`. `genes.tsv` 옆에.
- overlay off / EFO 미매칭 / 조회 실패 시 파일 생성 안 함(게이팅). 기존 annotate 로직·랭킹 불변.

### 4-1. `scripts/ot_complement.py` — 소스 변경
- **입력**: `--ot-scores <path>`(ot_scores.tsv = OT 전체), `--final <path>`(genes.tsv = 문헌 top-N),
  `--min-clinical`(default 0.0 초과), `--min-genetic`(default 0.5), `--top-k`(default 15),
  `--format {tsv,json}`.
- **로직**: ot_scores 행 중 `symbol ∉ final.symbol` **이고** (`ot_clinical > min-clinical` 또는
  `ot_genetic >= min-genetic`)인 타깃 선정 → **`ot_genetic` 내림차순 → `ot_clinical` 내림차순 → symbol
  오름차순** 정렬(genetic-forward, family-flooding 회피) → 상위 `top-k`.
- **출력**: TSV/JSON(stdout) — `symbol, ot_genetic, ot_clinical`. 없으면 빈 결과 + exit 0.
  `--ot-scores` 파일 부재 시 빈 결과 + exit 0(overlay off = 콜아웃 없음).
- **stdlib-only**, 랭킹·네트워크 책임 없음. 순수 file-in/stdout-out.
- **자체검증**: `--selftest` — final 제외, 임계값 경계(genetic `>=` / clinical strict `>`), top-k 절단,
  정렬 순서, 빈/부재 입력. assert 기반, 프레임워크 없음.

## 5. 가드레일 (기존 framing rule 계승 — `SKILL.md` L137)

- OT 점수는 **PMID로 인용 금지**, `verify_citations.py`에 **미포함**(문헌 인용만 검증), abstract 요약과
  **시각·의미적으로 분리**, 문구는 **"OpenTargets DB가 …도 보고함"**으로만. gene "발견"으로 서술 금지.

## 6. 임계값 (PLACEHOLDER — 실사용 보고 조정)

- B의 "OT 점수 높음" 컷: 잠정 `ot_clinical > 0` **또는** `ot_genetic >= 0.5`(gold 컷과 정합) + `top-k 15`.
- **미검증 표기**(lesson #7): 임계값이 헐거워도 top-k가 상위만 노출해 노이즈를 막는 구조. 실사용에서 콜아웃이
  너무 길거나(→ top-k↓ 또는 컷↑) 실타깃을 놓치면(→ 컷↓) 조정. 컷·top-k 확정 금지 전까지 "미검증" 표기.
- **held-out A 결과(2026-07-08)**: 상보성 7/8 질병 재현(면역 밖 포함) — B 착수 근거 확보. 상세 `dev_state.md`.

---

## 7. 완료 정의 (DoD)

- [x] A(held-out) 상보성 재현 판정 — 7/8 재현, 착수 확정(2026-07-08).
- [x] `fetch_genes.py --ot-overlay`가 `output/<slug>/ot_scores.tsv`(OT 전체 목록) 덤프(§4-0). `write_ot_scores`,
      overlay 성공 path에만. 포맷(symbol/ot_genetic/ot_clinical, sorted, round 3) helper와 일치 확인.
- [x] `scripts/ot_complement.py`: `--ot-scores`+`--final`+`--top-k`, genetic-forward 정렬, `--selftest`.
      Claude 독립 재검증 통과(breast cancer top = CHEK2·BRIP1·MSH6·PIK3CA…, tubulin flood 제거, overlay-off 게이트).
- [x] `write_ot_scores` seam 실검증: live OT 점수(RA)로 실제 덤프 함수 호출 → helper 관통 → CTLA4·CD40·TYK2·
      IL12B·IL23R 복제(Measurement B 헤드라인 재현). PubTator 재scan 없이 코드 seam 확정.
- [x] SKILL.md 반영: 노출 A(요약 컬럼+캡션), 노출 B(콜아웃 섹션+헬퍼 렌더 지시+게이팅), 방법 라인, overlay
      always-on(스킬 워크플로만; CLI 기본 off는 eval 순수성 유지), Mode A/B 진입분기.
- [x] 오프라인 회귀 전 통과(test_fetch_genes/pubmed/verify_citations + ot_complement/candidate_c selftest).
- [ ] **남은 e2e(실사용 수용)**: 실제 `--ot-overlay` 전체 run으로 LLM이 Phase 4 문서를 렌더 → 컬럼·콜아웃
      표시 + `verify_citations` 통과 + overlay-off 재run 시 문서 불변. LLM 렌더 단계라 다음 실사용에서 수용 확인.
- [x] `dev_state.md` 갱신.
