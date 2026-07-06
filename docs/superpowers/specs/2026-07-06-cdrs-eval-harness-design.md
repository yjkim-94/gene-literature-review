# CDRS eval harness — design (AD pilot)

> method_dev.md §7④. Built so we can say CDRS is "better" (or not) with numbers
> before wiring the placeholder-weighted rank_score into the ranking (§6.7 step 4).
> Scope: **atopic dermatitis (AD) pilot** — one disease, full pipeline, cheapest
> validation. Config-driven so 12-disease expansion is JSON edits, not code.

## Purpose

Quantitatively compare candidate gene-ranking formulas against an **external,
literature-independent** ground truth, so the CDRS `rank_score` (and its
placeholder weights) can be judged and tuned instead of asserted. The prior
increments (z_rel/breadth/track columns) are observe-only; this harness is the
measuring instrument that must exist before step 4 changes the actual ranking.

## Ground truth (OpenTargets only — DisGeNET is license-gated)

DisGeNET's curated download moved behind a paid license; free curated
alternatives (DISEASES/Jensen "knowledge" channel) are too sparse to rank
against (AD → 2 genes). OpenTargets is free via GraphQL and internally
aggregates ~10 genetic sources (GWAS Catalog, ClinVar/EVA, gene burden,
UniProt-genetics, Genomics England …), which is exactly what DisGeNET-curated
drew from.

- **gold set** = OT `genetic_association` datatype score ≥ τ (per-disease
  threshold in config). Independent of literature co-mention → breaks the
  circularity method_dev warns about.
- **secondary label** (not gold, reported separately) = OT `known_drug`
  (ChEMBL) — drug targets, also literature-independent. Matches method_dev's
  "보조 known-drug 별도 라벨".
- OT `literature` datatype is **excluded** — that is the circular channel.
- **negatives** for AUPRC = scored candidates not in gold; artifact class
  (Ig/TCR/HLA) is eval-only diagnostic, kept in the list.

Diseases map by MONDO id (OT) + PubTator entity token (fetch_genes). AD =
`MONDO_0004980` (atopic eczema) / `@DISEASE_Dermatitis_Atopic`.

## Execution model — offline ranking from one scored dump

Key property: the harness does **not** need §6.7 step 4. `fetch_genes --rank
cdrs` already writes `genes_all_scored.tsv` with every column (co_papers,
gene_papers, specificity, spec_adj, z_rel, breadth_random, hub_penalty, track).
The harness recomputes each ranking **offline from those columns**, so:

1. Run `fetch_genes --rank cdrs` on AD once (reuses the PubTator cache).
2. Load `all_scored.tsv` + M_D (OT or the run) + N (default 36e6).
3. Score six rankings over the candidates:
   - baselines: `co_papers`, `specificity`, `spec_adj` (current production),
     `enrichment_z` (computed from co, gene_papers, M_D, N), `z_rel` alone.
   - **CDRS** `rank_score` = artifact_weight · hub_penalty ·
     (0.60·P(z_rel) + 0.25·P(spec_adj) + 0.15·P(logFE)), where P(·) is the
     within-candidate percentile, logFE = log2(s_g / ((M_D+α)/(N+2α))),
     artifact_weight = 0.5 if track == "artifact" else 1.0. All derived from
     columns — no re-run, so weight grids can be swept offline.
4. Each ranking vs gold → **P@10, P@20, nDCG@20, AUPRC** (macro over diseases;
   one disease in the pilot).
5. Diagnostics: artifact-leakage (Ig/TCR/HLA fraction in top-N), hub-correctness
   (are broad hubs in `related_pleiotropic`), IL4/IL13 preservation.

## Components

- `evals/bench_diseases.json` — list of `{keyword, entity, mondo_id,
  genetic_threshold}`; AD only for the pilot.
- `evals/ground_truth.py` — OT GraphQL loader → `(gold_symbols, known_drug_symbols)`
  for a MONDO id; caches raw responses under `evals/.gt_cache/` (auditability +
  offline reruns).
- `evals/cdrs_bench.py` — orchestrator: ensure the scored dump exists (run
  fetch_genes if missing), load gold, compute the six rankings + metrics +
  diagnostics, write `evals/output/cdrs_bench_<disease>.md`.
- Metrics/stats are pure Python (no numpy — repo convention). paired Wilcoxon
  across diseases is deferred (meaningless with n=1); added at multi-disease.

## Testing

- Metric functions (`precision_at_k`, `ndcg_at_k`, `auprc`) get a small
  assert-based self-check with known inputs (no network).
- OT loader tested live against AD (FLG/IL13 must appear in the genetic gold).
- Harness end-to-end on AD produces the comparison table; the acceptance claim
  ("CDRS better") is NOT made from one disease — the pilot only proves the
  instrument works and shows the AD numbers.

## Out of scope (pilot)

Multi-disease macro averaging, paired Wilcoxon/bootstrap, tuning/held-out split,
weight grid search runs (the machinery allows it; we don't sweep yet), and any
"adopt CDRS" decision — all wait for the 12-disease expansion.
