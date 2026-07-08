# Task-aligned gold design (2026-07-07)

> **⚠ 폐기 (2026-07-08).** 이 설계에 따른 task-aligned recall eval은 폐기됨. GO-BP/Reactome/MSigDB gold는
> **pathway membership**을 재는데 이 skill은 **literature prominence**를 뽑으므로 construct가 달라, 관측된
> recall@30 0.14는 도구 실패가 아니라 gold-tool 불일치의 artifact다(gold를 늘려도 안 오름). OT literature
> score도 co-occurrence 기반이라 tautology. codex 2-agent 3라운드 토론 결론: 어떤 gold든 그 숫자를 "recall"로
> 부르면 안 됨. 필요 시엔 GWAS Catalog genetic-support overlap을 "literature-genetics gap" 지표로만 별도 report.
> 근거·경과는 `dev_state.md`(2026-07-08 항목) 참조. 아래 내용은 역사 기록으로만 보존.

## 목적

OpenTargets genetic gold는 stress test로 유지하되, main eval은 이 skill의 실제 목표인 "keyword 문헌 맥락에서 특이적으로 연구된 gene list"에 맞춘 gold로 별도 구성한다.

## Gold track

| track | keyword type | primary source | target size | note |
|---|---|---|---:|---|
| GO-BP | biological process | QuickGO / GO annotations | 30 genes | ferroptosis, autophagy처럼 GO term이 명확한 경우 |
| Reactome | pathway | Reactome pathway members | 30 genes | signaling/metabolism pathway에 적합 |
| MSigDB | curated gene set | MSigDB C2/C5/Hallmark | 30 genes | gene set 자체가 평가 단위일 때 적합 |
| Review-list | disease / phenotype | curated review table or guideline list | 20-30 genes | disease에서 문헌-context gold가 필요할 때 |
| OT-genetic | disease | OpenTargets genetic_association | 30 genes | main score 아님; stress test/overlay 검증 전용 |

## Selection rule

1. 각 keyword는 하나의 `gold_track`만 갖는다.
2. `gold_genes`는 source에서 기계적으로 추출하거나, review table에 명시된 목록만 사용한다.
3. LLM memory로 gene을 보충하지 않는다.
4. 30개 미만이면 억지로 채우지 않고 `gold_size_limit`에 이유를 기록한다.
5. source URL/ID, 추출일, 추출 rule을 `evals.json`에 남긴다.

## Suggested eval schema

```json
{
  "keyword": "autophagy",
  "entity": "",
  "gold_track": "GO-BP",
  "gold_source": "QuickGO GO:0006914, human taxon 9606, descendants",
  "gold_extracted_at": "2026-07-07",
  "gold_rule": "unique approved symbols; experimental evidence first; max 30",
  "gold_genes": []
}
```

## First pass

- Keep OT disease evals in `evals/evals.json` only if labelled `gold_track: OT-genetic`.
- Add 3-5 GO/Reactome/MSigDB process/pathway keywords first; they are cheaper and less ambiguous than disease review curation.
- Add disease review-list gold later, one disease at a time, because manual source audit is the slow part.

## First result

`evals/evals_task_aligned.json` uses 5 QuickGO GO-BP keywords with 30 genes each and `scan=500`. Mean recall@30 was 0.14. Most misses were `pool-miss`, so the next useful test is candidate discovery coverage, not another ranking tweak.
