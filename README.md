# gene-literature-review

A Claude skill that takes a keyword (disease, pathway, phenotype, etc.) and produces **① an accurate list of related genes → ② each gene's PubMed literature evidence**.

- **List-centric**: literature review is not for per-gene narrative summaries but the **evidence layer that validates list accuracy**. specificity value + representative PMID *is* the proof that "this gene is genuinely tied to the keyword."
- Small gene counts go through per-gene literature summaries (Phase 3); large ones (hundreds–1000) stop at the list + evidence values.

> **Which doc is which** — `SKILL.md` is the single source of truth for the operational workflow (the 4 phases, checkpoint formats, invariants) and is what an AI agent executes. This README is the human-facing overview: install, run commands, output columns, and design rationale. When workflow details matter, defer to `SKILL.md`; don't restate its steps here.

## Layout

```
gene-literature-review/
├── SKILL.md                4-phase workflow (gene list → collect literature → per-gene summary → integrate)
├── DESIGN.md               design rationale (loop-validation record — why it's built this way)
├── pipeline.html           animated end-to-end explainer (open in a browser)
├── scripts/
│   ├── fetch_genes.py      keyword → gene list (entity-grounded specificity ranking)
│   ├── fetch_pubmed.py     per-gene abstracts → files, PMC access-level labels
│   ├── runlog.py           shared per-phase logger (section headers + timestamped lines, live)
│   ├── test_fetch_genes.py ranking-logic self-check
│   └── test_fetch_pubmed.py abstract-XML parsing self-check (inline markup, pmcid)
└── evals/                  gene-list recall gold set + automatic measurement
```

Run:
```bash
cd gene-literature-review
# 1. resolve the keyword to a PubTator concept entity (pick one by paper count)
python scripts/fetch_genes.py --keyword "atopic dermatitis" --resolve
# 2. rank genes; writes output/<slug>/genes.tsv (+ genes_all_scored.tsv)
python scripts/fetch_genes.py --keyword "atopic dermatitis" --entity "@DISEASE_Dermatitis_Atopic" --max 20
```
Output is a tab-separated TSV (opens directly in Excel). `--entity` is optional — omit it for novel terms with no MeSH entity (free-text fallback). `--out` overrides the default run-dir path.

Each phase also writes a live progress log into the run dir — `phase1_fetch_genes.log` (SCAN/FILTER/SCORE/RESULT) and, once you run `fetch_pubmed.py`, `phase2_fetch_pubmed.log` (COLLECT/RESULT). Both use a section-header + timestamped-line format and flush per line, so a running phase is watchable with `tail -f output/<slug>/phase1_fetch_genes.log`.

### Output columns (`genes.tsv`)

| Column | Meaning |
|--------|---------|
| `symbol` | Gene symbol (from PubTator NER → NCBI esummary). |
| `gene_id` | NCBI Gene ID. |
| `name` | Full gene name. |
| `co_papers` | Papers where the gene entity co-occurs with the keyword/concept entity (specificity numerator). |
| `gene_papers` | Total papers with the gene entity, keyword or not (specificity denominator). |
| `specificity` | `co_papers / gene_papers` — how keyword-exclusive the gene is (1 = studied only in this keyword's context, ~0 = ubiquitous passenger). |
| `spec_adj` | Confidence-adjusted `specificity` (Wilson lower bound) — shrinks thinly-supported genes so a 3/3 ratio can't beat a core gene backed by hundreds. The sort key is this, with the artifact demotion below applied. |
| `below_floor` | `true` if `gene_papers` < `--min-gene-papers` (default 10): too little evidence, demoted to the bottom (not deleted). |
| `artifact` | `true` if the symbol is an immunoglobulin/TCR/HLA structural gene (e.g. IGHE) — a recurrent literature artifact. Its sort score is multiplied by 0.5 (demoted, not deleted); validated no-downside in `docs/cdrs-eval-findings.md`. |
| `evidence_pmids` | Up to 3 representative PMIDs from the entity co-occurrence query (`;`-joined) — real, verifiable evidence, never fabricated. |

Rows are sorted by `spec_adj` descending, after the 0.5× artifact demotion is applied to the sort score.

The script also writes a sidecar `genes_all_scored.tsv` (same columns) holding **every scored candidate before the `min_co`/`min_specificity` filter**, so the `spec_adj` cutoff can be judged against the full distribution instead of guessed.

## Core design (why it works this way)

The two failure modes this skill must prevent, in priority order:

### 1. Hallucination — invented genes / papers / associations
The pipeline has **no generative source of gene identity.** Symbols come only from PubTator NER GeneID → NCBI esummary, and PMIDs only from entity-grounded queries. The AI's roles (concept resolution · audit) are **strictly subtractive** and it **never names a gene** — the single invariant to enforce.

### 2. Irrelevant genes — passengers / mis-tags / wrong-disease genes leaking in
Defended in three layers.

- **Entity-based specificity** — `specificity = (papers where the @GENE_<id> entity co-occurs with the keyword) / (papers with the @GENE_<id> entity)`, both from PubTator search counts. **Not `[tiab]` string matching**: with string matching, `CAT` (catalase) matches "cat allergen" papers and gets poisoned; as an entity, `@GENE_CAT` resolves to catalase, so that contamination is blocked at the source. Aligning discovery and ranking on the same entity basis is this skill's root fix.
- **Wilson lower bound ranking** — rank by the lower confidence bound, not the point estimate (`co/total`), so a thinly-supported gene (3 of 3 papers = 1.0) can't beat a core gene backed by hundreds.
- **Low absolute denominator floor (n<10)** — only true artifacts (total papers < 10) are demoted (not deleted). A percentile floor was dropped — it penalizes a less-studied but highly specific top gene (FDX1, 1565 papers).
- **Structural-artifact demotion** — immunoglobulin/TCR/HLA symbols (e.g. IGHE) recur in disease abstracts as a literature artifact, not as drivers. Their sort score is halved (0.5×, demoted not deleted). A symbol-regex test, validated no-downside in `docs/cdrs-eval-findings.md`.

The key is that the passenger filter is **statistics, not AI**. Passengers have real co-abstracts, so a grounded AI answers "related" and can't discriminate core from passenger. The AI audit's only real role is **lexical disambiguation of common-word / short symbols** ("is CAT catalase or the animal here?").

### 3. Keyword expansion (search problem)
"아토피" (Korean) returns 0 hits in PubTator, and "atopy" misses the dominant term "atopic dermatitis," collapsing recall. → **Resolve the keyword to a PubTator concept entity** and pass it as `--entity` (e.g. `@DISEASE_Dermatitis_Atopic`). The specificity query becomes `"@GENE_<id>" AND "<entity>"`, which **unions the concept's surface synonyms** ("atopic eczema", "infantile eczema" → one disease entity) in a single exact call. **Not OR-expansion**: a grouping-less synonym OR collapses the PubTator parser (measured: `atopic dermatitis OR atopic eczema` → 20,466, *below* the single term's 66,111), and free-text synonyms are not auto-normalized. `python scripts/fetch_genes.py --keyword "<kw>" --resolve` lists the candidate entities with their paper counts so the concept is chosen by evidence, not by an AI's dominant-sense guess (blocks "AD"→Alzheimer mis-mapping); ambiguous / short keywords still require human confirmation. Novel terms with no MeSH entity (cuproptosis) omit `--entity` and proceed literal (free-text).

### 4. Token efficiency
Putting gene × paper × abstract into context makes cost grow quadratically. → **A script writes abstract text to files**, never loading it into the main context. With many genes, subagents fan out to burn tokens in their own contexts.

## Verification status

- **Ranking logic**: `python scripts/test_fetch_genes.py` — floor + Wilson lower bound demote artifacts and keep specific core genes on top.
- **Entity-grounded specificity (live)**: cuproptosis → FDX1(0.64) > DLAT > SLC31A1 > PDHA1, passengers (CD274/CDKN2A/PDCD1) all filtered out.
- **atopic dermatitis (entity `@DISEASE_Dermatitis_Atopic`)**: FLG (filaggrin, the top AD susceptibility gene), TSLP, IL31/IL13/STAT6/JAK1 etc. are real AD genes, zero hub/passenger contamination.
- **gene-list recall (evals)**: `python evals/run_eval.py`, mean recall@20 = 0.83.

## Not implemented (known gaps)

- **Numerator down-weighting** (for large reviews listing many genes) — the Wilson lower bound absorbs most of it, and per-paper fetching would be costly, so deferred.
- **Retraction filter** — excluding/marking retracted papers (`Retracted Publication` publication type); belongs to Phase 2, tracked separately.

See `DESIGN.md` for the design rationale and loop-validation history.

## Notes
- **NCBI API key (recommended).** Rate limit is 3 req/s without a key, 10 req/s with one — a big speedup on the scoring/collection loops. Get a free key at NCBI account → Settings → *API Key Management*, then set the `NCBI_API_KEY` env var (both scripts read it automatically):
  - PowerShell (persistent, new shells): `setx NCBI_API_KEY "your-key-here"`
  - PowerShell (current session only): `$env:NCBI_API_KEY = "your-key-here"`
  - bash/zsh: `export NCBI_API_KEY="your-key-here"` (add to `~/.bashrc` to persist)

  When it is not set, the scripts print a one-line reminder at startup, so first-time users always learn the key exists.
