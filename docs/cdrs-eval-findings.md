# CDRS evaluation — findings & recommendation (2026-07-06)

Status: **evaluation complete. Verdict adopted (2026-07-07): dropped CDRS,
shipped `spec_adj_artifact` (artifact demotion) as the default.**

> **Historical note:** the CDRS scoring code has since been removed
> (`scripts/data/panel_random.tsv`, `build_panel_random.py`, `fetch_genes.py
> --rank cdrs`, `evals/tune_weights.py`, the `--spec-only` flag). Only the
> artifact demotion (`is_artifact`) survives in the default ranking, and
> `evals/cdrs_bench.py` was reduced to a spec-only regression bench. Commands
> below that name those deleted files are the record of the experiment as run,
> not runnable instructions. See `dev_state.md`.

## Question

Does the CDRS cross-disease ranking (method_dev.md §5–6) rank keyword genes
better than the current production ranking (`spec_adj`, Wilson lower bound of
keyword specificity)? Judged against an external, literature-independent gold
(OpenTargets `genetic_association` score ≥ 0.5) so the test isn't circular.

## What was built

- `scripts/data/panel_random.tsv` — 30-disease B_random panel.
- `fetch_genes.py --rank cdrs` — observe-only columns: `z_rel`, `breadth_random`,
  `hub_penalty`, `pass_stage1`, `track` (ranking still `spec_adj`).
- `evals/` harness — recomputes 6 rankings offline from the scored columns and
  scores each vs the OT genetic gold (P@10/P@20/nDCG@20/AUPRC) + a cross-disease
  mean summary; `evals/tune_weights.py` sweeps the rank_score weights/toggles.

## Result (4 tuning diseases: AD, asthma, RA, psoriasis)

Mean across diseases:

| ranking | mean nDCG@20 | mean AUPRC |
|---------|--------------|------------|
| **spec_adj (current)** | **0.307** | **0.481** |
| specificity | 0.304 | 0.473 |
| z_rel (CDRS main signal) alone | 0.292 | 0.434 |
| CDRS rank_score (placeholder weights) | 0.292 | 0.422 |

- **The current `spec_adj` ranking wins.** CDRS with the placeholder weights is
  worse on both metrics. AD alone had looked like a CDRS win — that was
  confirmation bias (exactly the hazard method_dev §4 flagged); it did not
  generalize to asthma/RA/psoriasis.
- **Best tuned CDRS config only ties** spec_adj (nDCG 0.308, AUPRC 0.490) — a
  noise-level margin at 4 diseases with 4–8 gold each — and only by turning
  `hub_penalty` **off**.

### Which mechanisms carried their weight

Holding weights at the best combo, toggling the two multipliers:

| hub_penalty | artifact_weight | nDCG@20 | AUPRC |
|-------------|-----------------|---------|-------|
| off | off | 0.307 | 0.483 |
| off | **on** | 0.308 | 0.490 |
| **on** | off | 0.294 | 0.429 |
| **on** | on | 0.295 | 0.434 |

- `hub_penalty` (cross-disease breadth demotion) **consistently hurts**.
- `z_rel` (the intended main signal) earns weight ~0–0.2; the winning blend is
  mostly `spec_adj` (weight 0.5–0.7) with a `logFE` nudge.
- `artifact_weight` (Ig/TCR/HLA symbol demotion) is the **only** net-positive
  piece: ~+0.007 AUPRC, and it is cheap and independent of the whole panel.

## Confirmation on a larger candidate pool (scan 200 / max 30)

Re-run with a bigger pool (gold-in-candidates 7–11 per disease, up from 4–8) to
cut noise, and with `spec_adj_artifact` (= `artifact_weight × spec_adj`) as an
explicit ranking:

| ranking | mean nDCG@20 | mean AUPRC |
|---------|--------------|------------|
| **spec_adj_artifact** | **0.288** | **0.383** |
| spec_adj (current) | 0.282 | 0.364 |
| specificity | 0.280 | 0.359 |
| enrichment_z | 0.247 | 0.300 |
| z_rel | 0.222 | 0.274 |
| cdrs_rank_score (placeholder) | 0.217 | 0.259 |

- The bigger pool **strengthens** the conclusion: full `cdrs_rank_score` drops to
  the bottom tier; spec_adj's lead over the CDRS machinery is robust, not noise.
- `spec_adj_artifact` is **≥ spec_adj on every disease and strictly better where
  Ig/TCR/HLA genes appear** (asthma AUPRC 0.539 → 0.610, AD slightly up; RA and
  psoriasis tie because their candidate pools contain no artifact genes). It is
  a strict, no-downside win.

## Held-out reconfirmation of `spec_adj_artifact` (8 diseases, spec-only)

Ran the held-out 8 (IBD, T2D, Alzheimer, breast, melanoma, SLE, COPD, NAFLD)
with `--spec-only` (no panel — artifact demotion needs none). Breast cancer hit
a transient PubTator failure and was skipped; NAFLD had no gold-in-candidates;
6 diseases scored.

- `spec_adj_artifact` is **identical to `spec_adj` on every held-out disease**
  (melanoma a rounding whisker better on AUPRC). None of these diseases surface
  Ig/TCR/HLA genes in their candidate pool, so `artifact_weight` never fires.
- So across all 11 evaluated diseases (tuning-4 + held-out-7), artifact demotion
  is **strictly no-downside**: it helps on the allergic/IgE diseases where Ig
  genes contaminate the literature (AD, asthma), and is exactly neutral
  everywhere else. Zero regression risk.

## Recommendation

1. **Do not adopt CDRS as the default ranking.** Its two signature mechanisms
   (z_rel as main signal, cross-disease `hub_penalty`) do not help — hub_penalty
   is actively harmful — and the ~1,100 extra PubTator calls per keyword buy a
   worse result. Keep the `--rank cdrs` columns as an experimental/observe
   artifact only. Superseded: `--rank cdrs` was later removed; see the banner / `dev_state.md`.
2. **Adopt `artifact_weight` into the default ranking** — a symbol-regex demotion
   of Ig/TCR/HLA (IGHE etc.) applied on top of `spec_adj`. It is the best ranking
   measured, a strict no-downside improvement over the current one, and needs
   none of the panel machinery (near-zero cost: a regex on the symbol). This is
   the one piece of the CDRS work worth shipping.
3. **Held-out 8 diseases: not worth the spend for CDRS.** The bigger-pool result
   confirms CDRS loses; held-out would only reconfirm it. (A held-out check of
   `spec_adj_artifact` alone is cheap-ish if a formal sign-off is wanted before
   shipping it, since artifact demotion needs no panel — but the tuning-4 signal
   is already consistent and mechanism-clear.)

## Caveats

4 diseases; gold-in-candidates is tiny (4/6/4/8) so means are noisy. This is a
directional finding, not a significance test. But the direction is consistent
and the mechanism-level breakdown (hub_penalty hurts, z_rel unused) is the more
robust signal than the aggregate margin.
