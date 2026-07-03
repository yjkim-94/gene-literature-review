---
name: gene-literature-review
description: Use when a user gives a biological keyword (disease, pathway, phenotype, biological process, drug mechanism) and wants the genes associated with it AND a literature summary for each gene. This covers requests phrased as gene discovery even without the word "literature" -- "X에 관여하는 유전자 뭐가 있어", "what genes are involved in Y", "이 키워드 관련 gene 조사해줘/정리해줘", "유전자 문헌 조사", "gene 목록 뽑고 논문 정리", "literature review for genes in X", "keyword로 gene 찾고 요약". ALSO use when the user already has a gene list and wants each gene's PubMed literature summarized. Do NOT use for summarizing a single specific paper/PDF the user provides, for a general literature review not organized per-gene, or for pure sequence/variant/expression lookups with no literature component. The skill ranks genes by keyword-specificity (filtering out generic passenger genes), fetches abstracts via NCBI E-utilities into files (never dumping raw abstracts into context), then summarizes each gene with mandatory PMID citations and access-level labels.
---

# Gene Literature Review

Given a keyword (or a user-supplied gene list), proceed in order: **① related gene list → ② collect each gene's PubMed literature → ③ per-gene summary → ④ integrated document.**

## Design principles (why it works this way)

The goal is to prevent this skill's two biggest risks.

1. **Token blow-up**: putting gene × paper × abstract text into context makes cost grow quadratically with gene count. → **A script fetches the abstract text into files, not the LLM.** Raw abstract text is never loaded into the main context.
2. **Hallucination (invented papers / distorted summaries)**: literature review easily fabricates unread papers or misrepresents abstracts. → **Every claim cites a real PMID**, and each carries a label for how far the text was read (**abstract-only / full-text**).

## Phase 1 — Obtain the gene list

**First, route by request type:**

- **User supplied a gene list directly** ("do a literature review on geneA, geneB, geneC"): skip this phase. Write the given symbols into a one-column TSV with a `symbol` header (`output/genes.tsv`) and go to Phase 2. If there is no keyword, omit `--keyword` in fetch_pubmed to get **general gene literature** (representative papers for the gene itself, not keyword-specific association).
- **Keyword only** ("summarize genes related to atopy"): proceed below.
- **Large request (hundreds–1000)** ("1000 genes for atopy"): **list-centric mode** — see "Large requests" below.

```bash
python scripts/fetch_genes.py --keyword "<keyword>" --organism human --max 20 --out output/genes.tsv
```

`fetch_genes.py` picks genes in two steps. ① Use **PubTator3** to collect NER-tagged gene candidates from the keyword's papers — free-text NCBI Gene search only pushes generic hub genes (TP53/EGFR/APOE) to the top. ② Rerank candidates by **entity-based specificity**:

```
specificity = (papers where the gene ENTITY co-occurs with the keyword) / (papers with the gene entity)
```

Both counts come from PubTator `@GENE_<id>` search — **not `[tiab]` string matching.** This is the crux: `CAT` resolves to the catalase **entity**, so "cat allergen" papers don't leak in (string matching would poison it). Raw frequency alone lets passengers like CD274/CDKN2A rank high; specificity filters them out. Ranking uses the **Wilson lower bound (`spec_lower`), not the point estimate** — so a thinly-supported gene (3 of 3 papers = 1.0) can't beat a core gene backed by hundreds. On top of that a **low absolute denominator floor** demotes artifacts (total papers below `--min-gene-papers` are demoted, not deleted). The relative-percentile floor was dropped — it penalizes a less-studied but highly specific core gene (FDX1, 1565 papers) just for having fewer papers than its siblings (2000–3700). Output is a **tab-separated TSV** (opens directly in Excel) with columns `symbol · gene_id · name · co_papers · gene_papers · specificity · spec_lower · below_floor · evidence_pmids` (evidence_pmids is `;`-joined), sorted by `spec_lower` descending. Default thresholds: `--min-specificity 0.05` (applied to the lower bound), `--min-co 5`, `--min-gene-papers 10`.

`evidence_pmids` are representative PMIDs **from the entity co-occurrence query only** — string-query PMIDs may not mention the gene at all, so they are never used as evidence.

### Query confirmation gate (before searching)

Confirm the synonym expansion before firing the keyword verbatim — "아토피" (Korean) returns 0 hits in PubTator, and "atopy" misses the dominant literature term "atopic dermatitis," collapsing recall.

1. **Resolve the keyword to a MeSH concept.** Query NCBI MeSH to get candidate concepts (e.g. "아토피" → disease `Dermatitis, Atopic`, trait `Hypersensitivity, Immediate`).
2. **Concept selection** — if there is one candidate, use it. **If it splits into two or more**, each concept yields a different gene set, so pick one:
   - Choose the concept matching user intent from each candidate's **actually-fetched definition (scope note) and top co-mention genes** — grounded in the fetched definition, **not the AI's own knowledge**.
   - **Cross-check**: verify the chosen concept's top genes fit its definition biologically (e.g. `Dermatitis, Atopic` should have FLG/IL31/IL13 near the top).
   - **Ambiguous / short keywords ("AD", etc.) require human confirmation of the concept** — dominant-sense bias makes the wrong concept come back high-confidence, so no AI self-confidence auto-approve.
3. Within the **single chosen concept**, **OR-expand its entry terms (as actually fetched)** — same-concept synonyms only add recall with no contamination. **Assert each expansion term is a verbatim member** of the fetched entry-term list, drop it otherwise (blocks silent contamination from AI-guessed synonyms). Never OR together different concepts.
4. Show the expanded query (`term1 OR term2 OR ...`) to the user and **get confirmation**.
5. Novel terms with no MeSH (cuproptosis, etc.) have no synonym problem — proceed **literal**.
6. Pass the confirmed expanded query as `--keyword` (applied symmetrically to both discovery and specificity).

### Result review + AI audit (optional, at scale)

Read the result file and **confirm the gene list with the user first**. When the list is too large to review by hand, use an AI audit but **keep it narrow**:

- The AI audit is **not a relevance gate.** Passengers have real co-abstracts, so a grounded AI answers "related" for them too; core/passenger discrimination is the statistics' job (spec_lower · floor).
- The AI audit's only role is **lexical disambiguation of common-word / short symbols** ("is CAT catalase or the animal here?"). Check such symbols in the high-confidence band and **hard-drop confirmed mistags**.
- **Invariant: the AI never names a gene.** All symbols come only from PubTator NER → esummary. The AI's roles are subtractive (drop) and disambiguation only.

### Large requests (hundreds–1000): list-centric mode

For hundreds–1000 genes, skip per-gene literature summaries — collecting and summarizing 1000 abstracts is impractical and unnecessary for list accuracy. **The Phase 1 TSV (ranking · specificity · evidence PMIDs) is the final deliverable**; skip Phases 2–3 (optionally apply them only to a top-N).

- Scale up the size parameters: default `--cand-pool 40` caps candidates at 40. For `--max 1000`, set `--cand-pool` above the target (e.g. 1200) and `--scan` large (e.g. 400). PubTator makes 2 calls per candidate, so hundreds take ~10-20 min.
- Relax filters: at scale, recall comes first, so lower `--min-specificity` / `--min-co` to pass more through. The `spec_lower` sort still holds, so the top stays specific.
- **Realistic ceiling**: a keyword may not have 1000 truly specific genes. Return only as many as pass, and tell the user that count (don't inflate it).

## Phase 2 — Literature collection (script writes to files)

Collect abstracts for the confirmed gene list. **Do not read abstract text in this phase** — the script writes to files only.

```bash
python scripts/fetch_pubmed.py --genes output/genes.tsv --keyword "<keyword>" \
  --per-gene 5 --out-dir output/lit
```

Produces `output/lit/<symbol>.json` per gene. Each paper record:

```json
{"pmid": "12345678", "title": "...", "abstract": "...", "year": 2021,
 "journal": "...", "access": "full-text" | "abstract-only", "pmcid": "PMC..." | null}
```

`access` is `full-text` when a PMC open-access full text exists, else `abstract-only`. Only the top `--per-gene` papers (by relevance) are fetched per gene to bound scale.

## Phase 3 — Per-gene summary (identical template)

Summarize each gene from its `output/lit/<symbol>.json`. **Apply the exact same procedure and format to every gene** — varying depth or format per gene makes the integrated document uneven.

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
Read output/lit/<SYMBOL>.json only. Do not fetch anything.
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

Assemble the per-gene summaries into a final document. Always use this structure (the document is user-facing, so its headings stay Korean):

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

### When paywalled full text is genuinely needed (exception path)

Abstract + PMC OA full text is enough by default. If a specific paper's paywalled full text is truly needed, use **only legal, free OA paths** — WAF bypass (insane-search, etc.) fails on the publisher's Cloudflare challenge and isn't needed anyway. Branch on the paper record's `pmcid`:

**Branch A — `pmcid` exists (already collected in Phase 2): efetch from PMC directly.**
No need to go through Unpaywall. A paper in PMC has a settled location.
```bash
curl -s "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id=<PMC_number>&rettype=xml"
# <body> contains full INTRODUCTION/RESULTS/DISCUSSION sections
```

**Branch B — no `pmcid`: use Unpaywall (DOI) to find an OA location outside PMC.**
Only meaningful for finding a legal copy not in PMC (author repository, preprint (bioRxiv), publisher bronze OA).
```bash
curl -s "https://api.unpaywall.org/v2/<DOI>?email=<your-email>"
# check is_oa / oa_locations[]:
#   - host_type=repository with a PMC URL -> re-enter Branch A (efetch) with that PMCID
#   - otherwise (publisher PDF, preprint, etc.) -> use its url_for_pdf
```

If both fail (or there's no OA copy at all), proceed with the abstract only and mark it "(abstract only)" — do not fabricate.
