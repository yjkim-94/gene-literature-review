# gene-literature-review

A Claude skill that takes a keyword (disease, pathway, phenotype, etc.) and produces **① an accurate list of related genes → ② each gene's PubMed literature evidence**.

- **List-centric**: literature review is not for per-gene narrative summaries but the **evidence layer that validates list accuracy**. specificity value + representative PMID *is* the proof that "this gene is genuinely tied to the keyword."
- Small gene counts go through per-gene literature summaries (Phase 3); large ones (hundreds–1000) stop at the list + evidence values.

## Layout

```
gene-literature-review/
├── SKILL.md                4-phase workflow (gene list → collect literature → per-gene summary → integrate)
├── DESIGN.md               design rationale (loop-validation record — why it's built this way)
├── pipeline.html           animated end-to-end explainer (open in a browser)
├── scripts/
│   ├── fetch_genes.py      keyword → gene list (entity-grounded specificity ranking)
│   ├── fetch_pubmed.py     per-gene abstracts → files, PMC access-level labels
│   └── test_fetch_genes.py ranking-logic self-check
├── evals/                  gene-list recall gold set + automatic measurement
└── example/                atopy run example outputs (TSV + Markdown)
```

Run: `cd gene-literature-review && python scripts/fetch_genes.py --keyword "<keyword>" --max 20 --out output/genes.tsv` (tab-separated TSV — opens directly in Excel)

### Output columns (`genes.tsv`)

| Column | Meaning |
|--------|---------|
| `symbol` | Gene symbol (from PubTator NER → NCBI esummary). |
| `gene_id` | NCBI Gene ID. |
| `name` | Full gene name. |
| `co_papers` | Papers where the gene entity co-occurs with the keyword (specificity numerator). |
| `gene_papers` | Total papers with the gene entity, keyword or not (specificity denominator). |
| `specificity` | `co_papers / gene_papers` — how keyword-exclusive the gene is (1 = studied only in this keyword's context, ~0 = ubiquitous passenger). |
| `spec_lower` | Wilson lower bound of `specificity` — shrinks thinly-supported genes so a 3/3 ratio can't beat a core gene backed by hundreds. **This is the sort key.** |
| `below_floor` | `true` if `gene_papers` < `--min-gene-papers` (default 10): too little evidence, demoted to the bottom (not deleted). |
| `evidence_pmids` | Up to 3 representative PMIDs from the entity co-occurrence query (`;`-joined) — real, verifiable evidence, never fabricated. |

Rows are sorted by `spec_lower` descending.

## Core design (why it works this way)

The two failure modes this skill must prevent, in priority order:

### 1. Hallucination — invented genes / papers / associations
The pipeline has **no generative source of gene identity.** Symbols come only from PubTator NER GeneID → NCBI esummary, and PMIDs only from entity-grounded queries. The AI's roles (concept resolution · audit) are **strictly subtractive** and it **never names a gene** — the single invariant to enforce.

### 2. Irrelevant genes — passengers / mis-tags / wrong-disease genes leaking in
Defended in three layers.

- **Entity-based specificity** — `specificity = (papers where the @GENE_<id> entity co-occurs with the keyword) / (papers with the @GENE_<id> entity)`, both from PubTator search counts. **Not `[tiab]` string matching**: with string matching, `CAT` (catalase) matches "cat allergen" papers and gets poisoned; as an entity, `@GENE_CAT` resolves to catalase, so that contamination is blocked at the source. Aligning discovery and ranking on the same entity basis is this skill's root fix.
- **Wilson lower bound ranking** — rank by the lower confidence bound, not the point estimate (`co/total`), so a thinly-supported gene (3 of 3 papers = 1.0) can't beat a core gene backed by hundreds.
- **Low absolute denominator floor (n<10)** — only true artifacts (total papers < 10) are demoted (not deleted). A percentile floor was dropped — it penalizes a less-studied but highly specific top gene (FDX1, 1565 papers).

The key is that the passenger filter is **statistics, not AI**. Passengers have real co-abstracts, so a grounded AI answers "related" and can't discriminate core from passenger. The AI audit's only real role is **lexical disambiguation of common-word / short symbols** ("is CAT catalase or the animal here?").

### 3. Keyword expansion (search problem)
"아토피" (Korean) returns 0 hits in PubTator, and "atopy" misses the dominant term "atopic dermatitis," collapsing recall. → **Resolve the keyword to a MeSH concept, expand to its entry terms**, assert each expansion term is a verbatim member of the fetched list (blocks AI-guessed synonyms like "AD"→Alzheimer), and require human confirmation for ambiguous / short keywords. Novel terms with no MeSH (cuproptosis) proceed literal.

### 4. Token efficiency
Putting gene × paper × abstract into context makes cost grow quadratically. → **A script writes abstract text to files**, never loading it into the main context. With many genes, subagents fan out to burn tokens in their own contexts.

## Verification status

- **Ranking logic**: `python scripts/test_fetch_genes.py` — floor + Wilson lower bound demote artifacts and keep specific core genes on top.
- **Entity-grounded specificity (live)**: cuproptosis → FDX1(0.64) > DLAT > SLC31A1 > PDHA1, passengers (CD274/CDKN2A/PDCD1) all filtered out.
- **atopy (subagent, `example/`)**: FLG (filaggrin, the top atopic-dermatitis susceptibility gene) ranks 2nd, IL31/IL13/STAT6/JAK1 etc. are real AD genes, zero hub/passenger contamination.
- **gene-list recall (evals)**: `python evals/run_eval.py`, mean recall@20 = 0.83.

## Not implemented (known gaps)

- **Numerator down-weighting** (for large reviews listing many genes) — the Wilson lower bound absorbs most of it, and per-paper fetching would be costly, so deferred.
- **Retraction filter** — excluding/marking retracted papers (`Retracted Publication` publication type); belongs to Phase 2, tracked separately.

See `DESIGN.md` for the design rationale and loop-validation history.

## Notes
- NCBI/PubTator rate limit: 3 req/s without a key. Set the `NCBI_API_KEY` env var to automatically use 10 req/s.
