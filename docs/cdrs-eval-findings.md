# CDRS evaluation — findings & recommendation (2026-07-06)

Status: **evaluation complete on the tuning-4 set. Decision pending (user).**

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

## Recommendation

1. **Do not adopt CDRS as the default ranking.** Its two signature mechanisms
   (z_rel as main signal, cross-disease `hub_penalty`) do not help — hub_penalty
   is actively harmful — and the ~1,100 extra PubTator calls per keyword buy a
   net-neutral-to-worse result. Keep `--rank spec` (current) as default; the
   `--rank cdrs` columns stay as an experimental/observe artifact.
2. **Consider adopting only `artifact_weight`** — a symbol-regex demotion of
   Ig/TCR/HLA (e.g. IGHE) applied on top of `spec_adj`. It is the one separable
   improvement, near-zero cost, and needs none of the panel machinery.
3. **Held-out 8 diseases: likely not worth the spend.** The tuning-set ceiling
   is a noise-level tie reached only by disabling CDRS's core idea, so held-out
   validation would almost certainly confirm "no real improvement." Run it only
   if a formal negative result is wanted for the record.

## Caveats

4 diseases; gold-in-candidates is tiny (4/6/4/8) so means are noisy. This is a
directional finding, not a significance test. But the direction is consistent
and the mechanism-level breakdown (hub_penalty hurts, z_rel unused) is the more
robust signal than the aggregate margin.
