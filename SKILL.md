---
name: gene-literature-review
description: Use when a user gives a biological keyword (disease, pathway, phenotype, biological process, drug mechanism) and wants the genes associated with it AND a literature summary for each gene. This covers requests phrased as gene discovery even without the word "literature" -- "X에 관여하는 유전자 뭐가 있어", "what genes are involved in Y", "이 키워드 관련 gene 조사해줘/정리해줘", "유전자 문헌 조사", "gene 목록 뽑고 논문 정리", "literature review for genes in X", "keyword로 gene 찾고 요약". ALSO use when the user already has a gene list and wants each gene's PubMed literature summarized. Do NOT use for summarizing a single specific paper/PDF the user provides, for a general literature review not organized per-gene, or for pure sequence/variant/expression lookups with no literature component. The skill ranks genes by keyword-specificity (filtering out generic passenger genes), fetches abstracts via NCBI E-utilities into files (never dumping raw abstracts into context), then summarizes each gene with mandatory PMID citations and access-level labels.
---

# Gene Literature Review

Given a keyword (or a user-supplied gene list), proceed in order: **① related gene list → ② collect each gene's PubMed literature → ③ per-gene summary → ④ integrated document.**

### Run directory (artifact naming — one place, everything chains off it)

Every artifact of a single run lives under one **run directory** `output/<slug>/`, where `<slug>` is the confirmed keyword as lowercase kebab-case (`atopic dermatitis` → `atopic-dermatitis`). Fixed layout, so separate keywords never overwrite each other and each step finds its input by location:

```
output/<slug>/
  genes.tsv                     # Phase 1 ranked list
  genes_all_scored.tsv          # Phase 1 pre-filter sidecar (auto)
  lit/<SYMBOL>.json             # Phase 2 abstracts, one file per gene
  gene_literature_review.md     # Phase 4 final document
```

The slug is computed **once**, by `fetch_genes.py` from `--keyword`; downstream scripts derive their paths from the run dir (`fetch_pubmed.py` writes `lit/` next to `--genes`), so pass paths that stay inside `output/<slug>/` and never re-slug by hand. A user-supplied gene list (no keyword) has no slug — use `output/manual/` as the run dir.

## Design principles (why it works this way)

The goal is to prevent this skill's two biggest risks.

1. **Token blow-up**: putting gene × paper × abstract text into context makes cost grow quadratically with gene count. → **A script fetches the abstract text into files, not the LLM.** Raw abstract text is never loaded into the main context.
2. **Hallucination (invented papers / distorted summaries)**: literature review easily fabricates unread papers or misrepresents abstracts. → **Every claim cites a real PMID**, and each carries a label for how far the text was read (**abstract-only / full-text**).

## User-facing output format (fixed — use verbatim every run)

Every checkpoint shown to the user uses the **same block**: a `■ Phase N · <단계>` header, aligned `라벨 : 값` lines, and an optional `⚠` / `→` line. **Put a blank line between logical groups** (header ↔ 값 ↔ caveat/prompt) so each block breathes. Fill the blanks; do not vary the structure, labels, or order between runs (consistency across runs is the whole point). Labels stay Korean; machine tokens (paths, `spec_adj`, `--max`) stay literal. These fire **one at a time** across the run (never stacked), separated by the user's replies.

```
■ Phase 1 · Query gate

keyword(입력) : <원문>
canonical    : <MeSH 확정 term>   (<concept 후보 수>개 중 선택)
organism     : <human/mouse/...>

→ 이대로 진행할까요?
```

```
■ Phase 1 · Preflight

논문수   : <count>편
scan     : <N>편  (~<추정>분, 1,000편당 1-2분)
organism : <organism>
max      : <max>

⚠ 스캔 전 gene 수 미확정 — max(<max>)만큼 안 채워질 수 있음
```

```
■ Phase 1 · Scan 완료

scan      : <N>편 완료
후보 gene : <후보수>개

→ 상위 <4×max>개(=4×max) scoring 시작
```

```
■ Phase 1 · 결과

scored : <scored>개 → 필터 통과 <통과수>개
저장   : output/<slug>/genes.tsv
전량   : genes_all_scored.tsv

[core/특이]         상위 <a>개  (high spec_adj)
[관련-pleiotropic]  별도 <b>개  (high co_papers, low spec_adj)

→ gene 목록 확인해 주세요
```

```
■ Phase 2 · 문헌 수집 완료

gene      : <N>개 · gene당 상위 <per-gene>편
저장      : output/<slug>/lit/<symbol>.json
full-text : <ft>편 / abstract-only : <ab>편
```

```
■ Phase 3 · Gene별 요약 완료

방식 : <sequential | subagent N개>
완료 : <N>개 gene
```

```
■ Phase 4 · 통합 문서 완료

저장 : output/<slug>/gene_literature_review.md
gene : <N>개 · 근거 논문 <총합>편

→ .docx 변환할까요? (md-to-docx)
```

Large-request / list-centric mode ends at the `Phase 1 · 결과` block (Phases 2–4 skipped) — say so on that block instead of showing the later ones.

## Phase 1 — Obtain the gene list

**First, route by request type:**

- **User supplied a gene list directly** ("do a literature review on geneA, geneB, geneC"): skip this phase. Write the given symbols into a one-column TSV with a `symbol` header at `output/manual/genes.tsv` and go to Phase 2. If there is no keyword, omit `--keyword` in fetch_pubmed to get **general gene literature** (representative papers for the gene itself, not keyword-specific association).
- **Keyword only** ("summarize genes related to atopy"): proceed below.
- **Large request (hundreds–1000)** ("1000 genes for atopy"): **list-centric mode** — see "Large requests" below.

```bash
python scripts/fetch_genes.py --keyword "atopic dermatitis" --entity "@DISEASE_Dermatitis_Atopic" --organism human --max 20
# --entity (token from `--resolve`) unions the concept's synonyms.
# writes output/<slug>/genes.tsv (+ genes_all_scored.tsv). --out overrides.
```

`fetch_genes.py` picks genes in two steps. ① Use **PubTator3** to collect NER-tagged gene candidates from the concept's papers — free-text NCBI Gene search only pushes generic hub genes (TP53/EGFR/APOE) to the top. ② Rerank candidates by **entity-based specificity**:

```
specificity = (papers where the gene ENTITY co-occurs with the keyword/concept) / (papers with the gene entity)
```

Both counts come from PubTator `@GENE_<id>` search — **not `[tiab]` string matching.** This is the crux: `CAT` resolves to the catalase **entity**, so "cat allergen" papers don't leak in (string matching would poison it). **The keyword side is also an entity when `--entity @DISEASE_MESH:<id>` is passed** (from the gate's MeSH resolution): both discovery and the numerator query become `"@GENE_<id>" AND "@DISEASE_MESH:<id>"`, which **unions the concept's surface synonyms** ("atopic eczema", "infantile eczema" → one MeSH disease entity) in a single exact call. This is why OR-expansion is neither needed nor allowed — grouping-less synonym OR *collapses* the PubTator parser (measured: `atopic dermatitis OR atopic eczema` → 20,466, *below* the single term's 66,111), while the entity does the union natively. Novel terms with no MeSH (cuproptosis) omit `--entity` and fall back to free-text `--keyword`. Raw frequency alone lets passengers like CD274/CDKN2A rank high; specificity filters them out. Ranking uses the **Wilson lower bound (`spec_adj`), not the point estimate** — so a thinly-supported gene (3 of 3 papers = 1.0) can't beat a core gene backed by hundreds. On top of that a **low absolute denominator floor** demotes artifacts (total papers below `--min-gene-papers` are demoted, not deleted). The relative-percentile floor was dropped — it penalizes a less-studied but highly specific core gene (FDX1, 1565 papers) just for having fewer papers than its siblings (2000–3700). Output is a **tab-separated TSV** (opens directly in Excel) with columns `symbol · gene_id · name · co_papers · gene_papers · specificity · spec_adj · below_floor · evidence_pmids` (evidence_pmids is `;`-joined), sorted by `spec_adj` descending. Default thresholds: `--min-specificity 0.05` (applied to the lower bound), `--min-co 5`, `--min-gene-papers 10`.

**Scoring is bounded by `--max`, not by scan size.** Specificity scoring costs 2 PubTator calls per candidate (the dominant cost), so only the **top `4 × --max` candidates by co-mention** get scored (`SCORE_MULTIPLE` in the script). Organism is filtered *first*, on the cheap batched esummary, so the 2-call scoring never runs on a non-`--organism` gene. The `4×` headroom absorbs filter + organism dropout so `--max` genes still survive; if a keyword's true specific-gene count is smaller, fewer come back (never inflated). The co-mention prefilter doubles as an artifact cut — one-off NER mistags in the long tail never reach scoring. There is **no `--cand-pool`** (removed; it was a manual guess for this pool — now derived from `--max`).

Alongside `genes.tsv`, the script always writes a sidecar `genes_all_scored.tsv` — **every scored candidate before the `min_co`/`min_specificity` filter**, same columns, sorted by `spec_adj`. Read it to set the cutoff from the actual `spec_adj` distribution (does 0.05 land on a real gap, or slice through a smooth run?) and to see exactly which gene was the first one cut and by how much — the filtered `genes.tsv` alone can't show that.

`evidence_pmids` are representative PMIDs **from the entity co-occurrence query only** — string-query PMIDs may not mention the gene at all, so they are never used as evidence.

### Query confirmation gate (before searching)

Resolve the keyword to a concept entity before firing it verbatim — "아토피" (Korean) returns 0 hits in PubTator, and "atopy" misses the dominant literature term "atopic dermatitis," collapsing recall. Use `python scripts/fetch_genes.py --keyword "<kw>" --resolve` to list candidate entities with paper counts (objective, not an AI guess).

1. **Resolve the keyword to a concept-entity token (objective).** Run `python scripts/fetch_genes.py --keyword "<kw>" --resolve` — it returns PubTator autocomplete candidates as `token · biotype · count · name` (e.g. `@DISEASE_Dermatitis_Atopic · disease · 64350 · Dermatitis Atopic`). The `token` is used verbatim as `--entity`. Empty output ⇒ novel term with no entity ⇒ free-text fallback. (The `@DISEASE_MESH:D003876` form is equivalent to the token form; either works.)
2. **Concept selection** — if there is one candidate, use it. **If it splits into two or more**, each concept yields a different gene set, so pick one:
   - Choose the concept matching user intent from each candidate's **actually-fetched definition (scope note) and top co-mention genes** — grounded in the fetched definition, **not the AI's own knowledge**.
   - **Cross-check**: verify the chosen concept's top genes fit its definition biologically (e.g. `Dermatitis, Atopic` should have FLG/IL31/IL13 near the top).
   - **Ambiguous / short keywords ("AD", etc.) require human confirmation of the concept** — dominant-sense bias makes the wrong concept come back high-confidence, so no AI self-confidence auto-approve.
3. **Pass the concept as an entity, not OR-expanded synonyms.** Give `--keyword "<preferred name>"` (for the slug/label) **and `--entity "<token>"`** (from step 1, e.g. `@DISEASE_Dermatitis_Atopic`). The script queries `"@GENE_<id>" AND "<token>"` (each token quoted — an unquoted `:` in the `@DISEASE_MESH:D…` form 400s), which **unions the concept's surface synonyms natively** ("atopic eczema", "infantile eczema" all map to the one disease entity). Do **NOT** OR-expand entry terms into `--keyword`: a grouping-less multiword OR mis-scopes the PubTator `AND` and *collapses* `co_papers` (measured: FLG free-text `... OR ...` → **25**; even `atopic dermatitis OR atopic eczema` at search level → 20,466, *below* the single term's 66,111). Free-text synonyms are **not** auto-normalized (each returns a different count and different top papers) — only the **entity** unions them, in one exact call.
4. Show the chosen term (and which MeSH entity it maps to) to the user and **get confirmation**.
5. Novel terms with no MeSH (cuproptosis, etc.) have no entity — omit `--entity` and pass `--keyword` **literal** (free-text fallback).
6. The confirmed `--entity` (or free-text `--keyword` fallback) is applied symmetrically to both discovery and specificity.

### Preflight (count → scan / organism) — before running the script

Once the canonical term is fixed, do a **one-call preflight** so the user sets scan depth and organism with real numbers, not guesses:

```bash
# total papers for the confirmed concept (the `count` field).
# with entity: text="<token>" (quoted) -- the synonym-union universe.
# without: url-encode the free-text keyword.
curl -s "https://www.ncbi.nlm.nih.gov/research/pubtator3-api/search/?text=%22@DISEASE_Dermatitis_Atopic%22" | python -c "import sys,json;print(json.load(sys.stdin)['count'])"
```

Note: `--resolve` already prints each candidate's count, so if you resolved there you can skip this call.

Then report and confirm:

1. **Total papers** for the concept (entity count, e.g. `@DISEASE_Dermatitis_Atopic` → 64,350). This is the scan universe.
2. **Scan time**: NER runs ~**1–2 min per 1,000 papers** scanned. State this so the estimate isn't mistaken for the whole run — **scoring (after candidates are known) is the dominant, separate cost** and can't be estimated until the candidate count is in.
3. **Caveat**: the distinct-gene count is unknown until the scan runs, so **`--max` may not fill** — a keyword may simply not have that many specific genes. Don't promise the full number.
4. **Ask `--scan` and `--organism`** here (organism is only used post-scan in the esummary filter, so this is the latest it can be set). Do *not* prescribe a scan number — present the total and let the user choose.
5. After the scan, **report the candidate gene count** ("N gene candidates found") and proceed to scoring without a second gate — scoring volume is already bounded at `4 × --max`.

### Result review + AI audit (optional, at scale)

Read the result file and **confirm the gene list with the user first**. When the list is too large to review by hand, use an AI audit but **keep it narrow**:

- The AI audit is **not a relevance gate.** Passengers have real co-abstracts, so a grounded AI answers "related" for them too; core/passenger discrimination is the statistics' job (spec_adj · floor).
- The AI audit's only role is **lexical disambiguation of common-word / short symbols** ("is CAT catalase or the animal here?"). Check such symbols in the high-confidence band and **hard-drop confirmed mistags**.
- **Invariant: the AI never names a gene.** All symbols come only from PubTator NER → esummary. The AI's roles are subtractive (drop) and disambiguation only.

**Read spec_adj and co_papers as two axes, not one hard cut.** `spec_adj` is keyword *specificity*, not keyword *relatedness*. A pleiotropic hub gene truly central to the keyword (IL4, STAT6, CD8A for atopy) has a huge total-paper denominator, so its specificity is structurally suppressed and it sinks below the cutoff — a false negative (measured: IL4 co=8409, overwhelming evidence, yet spec_adj ~0.083, mid-low). And in the boundary band the `spec_adj` curve is smooth (0.018 → 0.008 with no elbow), so a single hard threshold has no natural place to fall — it will always clip a legitimate near-miss (e.g. a known keyword miRNA landing just under 0.015). So don't report one thresholded list as the whole answer. Read `genes_all_scored.tsv` on both axes and label **two zones**: **core/specific** (high `spec_adj`) and **related-but-pleiotropic** (high `co_papers`, low `spec_adj`) — surface the second zone's high-`co` genes explicitly instead of letting the specificity cut bury them. (A relative-percentile floor is not the fix — it was already dropped for demoting niche core genes; keep the absolute floor and add the co-axis read on top.)

### Large requests (hundreds–1000): list-centric mode

For hundreds–1000 genes, skip per-gene literature summaries — collecting and summarizing 1000 abstracts is impractical and unnecessary for list accuracy. **The Phase 1 TSV (ranking · specificity · evidence PMIDs) is the final deliverable**; skip Phases 2–3 (optionally apply them only to a top-N).

- Scale up `--scan` and `--max`. Scoring volume is `4 × --max` (no `--cand-pool` anymore), so `--max 1000` scores up to ~4,000 candidates automatically. Raise `--scan` well above `--max` (e.g. `--scan 3000` for `--max 1000`) so the candidate pool is deep enough to fill the target. PubTator makes 2 calls per scored candidate, so thousands take tens of minutes to hours — quote the estimate up front.
- Relax filters: at scale, recall comes first, so lower `--min-specificity` / `--min-co` to pass more through. The `spec_adj` sort still holds, so the top stays specific.
- **Realistic ceiling**: a keyword may not have 1000 truly specific genes. Return only as many as pass, and tell the user that count (don't inflate it).

## Phase 2 — Literature collection (script writes to files)

Collect abstracts for the confirmed gene list. **Do not read abstract text in this phase** — the script writes to files only.

```bash
python scripts/fetch_pubmed.py --genes output/<slug>/genes.tsv --keyword "<keyword>" \
  --per-gene 5
# writes output/<slug>/lit/ by default (next to --genes). --out-dir overrides.
```

Produces `output/<slug>/lit/<symbol>.json` per gene. Each paper record:

```json
{"pmid": "12345678", "title": "...", "abstract": "...", "year": 2021,
 "journal": "...", "access": "full-text" | "abstract-only", "pmcid": "PMC..." | null}
```

`access` is `full-text` when a PMC open-access full text exists, else `abstract-only`. Only the top `--per-gene` papers (by relevance) are fetched per gene to bound scale.

## Phase 3 — Per-gene summary (identical template)

Summarize each gene from its `output/<slug>/lit/<symbol>.json`. **Apply the exact same procedure and format to every gene** — varying depth or format per gene makes the integrated document uneven.

### 9 or fewer genes: sequential in the main context

Read one gene file at a time and summarize with the template below. After processing a gene, do not reference its raw text again.

### 10 or more genes: subagent fan-out (even batch split)

Set the number of subagents and each batch size from the gene count `N`:

- **agents = min(8, ⌈N / 10⌉)** — target up to 10 genes per agent, but **cap concurrent agents at 8** (rate limit / manageability). When capped at 8, batch size exceeds 10.
- Split genes **as evenly as possible** into batches, one per agent. Distribute the remainder one at a time starting from the first batch.
  - e.g. 10 → 1[10] · 11 → 2[6/5] · 20 → 2[10/10] · 21 → 3[7/7/7] · 35 → 4[9/9/9/8] · 90 → **8**[12×6/11×2]
- If genes are very numerous (batch per agent gets excessive), it's really a large request — consider Phase 1 list-centric mode instead.
- Each subagent's **model is sonnet** — reading a file and filling a fixed template is a bounded task, matching cost, speed, and citation discipline.

Each agent reads only its batch's gene files, burning the abstract tokens in the subagent context and returning only summaries to the main context. **Give every subagent the exact same prompt verbatim** (substituting each `<SYMBOL>` in the batch) — any drift in instructions splits the output format across genes.

The output labels in the prompt below are the user-facing document and stay Korean:

```
Read output/<slug>/lit/<SYMBOL>.json only. Do not fetch anything.
Summarize gene <SYMBOL> using ONLY the abstracts in that file, following this exact template:

### <SYMBOL> — <full gene name>
- **키워드와의 연관성**: 2~3문장. 각 주장 끝에 근거 PMID를 [PMID:xxxxxxxx] 형식으로 단다.
- **주요 발견**: 불릿 2~4개. 각 불릿에 PMID 인용 필수.
- **근거 논문**: 표 | PMID | 연도 | 접근수준 | 한 줄 요지 |

Rules:
- Cite ONLY PMIDs that exist in the file. Never invent a PMID or a finding.
- If a claim is from an abstract-only paper, that is fine — the access column records it.
- If the file has no papers, write "관련 문헌 없음" and stop.
Return only the filled template, nothing else.
```

If a batch has 2 or more genes, instruct the agent to apply the prompt above to each SYMBOL in the batch — read each gene file one by one, fill the template block per gene, and return them concatenated in order.

**When there is no keyword** (user supplied only a gene list): change the first item's label from `키워드와의 연관성` to **`핵심 문헌 요지`** and summarize the gene's own representative research. All other formatting and PMID citation rules are identical.

## Phase 4 — Integrated document

Assemble the per-gene summaries into a final document. **Save it as `output/<slug>/gene_literature_review.md`** (fixed filename, inside the run dir next to `genes.tsv`/`lit/`) unless the user names another path. Always use this structure (the document is user-facing, so its headings stay Korean):

```markdown
# <keyword> 관련 Gene 문헌 조사

## 요약 (한눈에 보기)
| Gene | 키워드 연관성 (한 줄) | 근거 논문 수 | 최신 연도 |
|------|----------------------|-------------|----------|

## Gene별 상세
<Phase 3의 gene별 요약을 그대로 이어붙임>

## 방법
- Gene 목록: NCBI Gene, keyword="<keyword>", organism=<...>, N=<...>
- 문헌: PubMed E-utilities, gene당 상위 <per-gene>편, 수집일 <YYYY-MM-DD>
- 접근수준: full-text=PMC open-access 전문 확인, abstract-only=abstract만 확인
```

At the end, if the user wants it, offer `.docx` conversion via the `md-to-docx` skill.

## Notes

- NCBI E-utilities has a rate limit (3 req/s without a key). The scripts handle it with sleeps and, if the `NCBI_API_KEY` env var is set, automatically use it to raise the limit to 10 req/s.
- **Paywalled full text** is almost never needed — abstract + PMC OA full text covers the gene summaries. On the rare occasion a specific paper's paywalled full text is genuinely required, read [`docs/paywalled-access.md`](docs/paywalled-access.md) for the legal free-OA retrieval paths (PMC efetch / Unpaywall). Do not fabricate; mark "(abstract only)" if no OA copy exists.
