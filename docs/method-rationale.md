# Method rationale (why the skill works this way)

Background, measured numbers, and derivations extracted from `SKILL.md`. The
skill's `SKILL.md` keeps the **procedure**; this file holds the **justification**
you consult when a design choice is questioned or being changed. Nothing here is
a step to execute — it explains *why* the steps are what they are.

## Design principles — the two risks this skill defends against

The whole pipeline exists to prevent this skill's two biggest failure modes:

1. **Token blow-up**: putting gene × paper × abstract text into context makes
   cost grow quadratically with gene count. → **A script fetches the abstract
   text into files, not the LLM.** Raw abstract text is never loaded into the
   main context.
2. **Hallucination (invented papers / distorted summaries)**: literature review
   easily fabricates unread papers or misrepresents abstracts. → **Every claim
   cites a real PMID**, and after the summary is written `verify_citations.py`
   **mechanically re-checks** that every cited PMID actually exists in that
   gene's collected file (a string comparison — the verifier itself can't
   hallucinate). Each paper carries an **access label**: `full-text` = a free
   PMC open-access full text *exists*, `abstract-only` = only the abstract is
   public. **The summary is built from the abstract in either case**, so the
   label marks availability, not how deeply the paper was read. **Retracted
   papers are flagged** (`retracted`) and dropped from the evidence.

## Phase 1 — why entity-specificity, Wilson lower bound, and the floor

**Why PubTator entities, not free-text.** Free-text NCBI Gene search only pushes
generic hub genes (TP53/EGFR/APOE) to the top; PubTator3 NER-tagged candidates
avoid that. Both specificity counts come from PubTator `@GENE_<id>` search — not
`[tiab]` string matching. This is the crux: `CAT` resolves to the catalase
**entity**, so "cat allergen" papers don't leak in (string matching would poison
it).

**Why the entity unions synonyms and OR-expansion is banned.** When
`--entity @DISEASE_MESH:<id>` is passed, both discovery and the numerator query
become `"@GENE_<id>" AND "@DISEASE_MESH:<id>"`, which unions the concept's
surface synonyms ("atopic eczema", "infantile eczema" → one MeSH disease entity)
in a single exact call. OR-expansion is neither needed nor allowed —
grouping-less synonym OR *collapses* the PubTator parser (measured:
`atopic dermatitis OR atopic eczema` → 20,466, *below* the single term's 66,111),
while the entity does the union natively. Novel terms with no MeSH (cuproptosis)
omit `--entity` and fall back to free-text `--keyword`.

**Why Wilson lower bound, not the point estimate.** Raw frequency alone lets
passengers like CD274/CDKN2A rank high; specificity filters them out. Ranking
uses the Wilson lower bound (`spec_adj`) so a thinly-supported gene (3 of 3
papers = 1.0) can't beat a core gene backed by hundreds.

**Why an absolute floor, not a relative percentile.** A low absolute denominator
floor demotes artifacts (total papers below `--min-gene-papers` are demoted, not
deleted). The relative-percentile floor was dropped — it penalizes a
less-studied but highly specific core gene (FDX1, 1565 papers) just for having
fewer papers than its siblings (2000–3700).

**Why the structural-artifact demotion.** Immunoglobulin/TCR/HLA symbols (e.g.
IGHE) are recurrent literature artifacts, not disease drivers, so their sort
score is halved (0.5×, demoted not deleted) via a symbol-regex test — validated
no-downside in `docs/cdrs-eval-findings.md`.

**Why `5 × --max` scoring headroom.** Specificity scoring costs 2 PubTator calls
per candidate (the dominant cost), so only the top `5 × --max` scan candidates by
co-mention get scored. The `4×` headroom (over the final `--max`) absorbs filter
+ organism dropout so `--max` genes still survive; if a keyword's true
specific-gene count is smaller, fewer come back (never inflated). The co-mention
prefilter doubles as an artifact cut — one-off NER mistags in the long tail never
reach scoring.

## Phase 1 — why the OpenTargets overlay is complementary, not a ranking input

Its measured value is *complementary*, not a replacement: OpenTargets surfaces
genetic/clinically-drugged targets that co-occurrence under-ranks or misses
entirely (e.g. breast cancer CHEK2/KRAS/PIK3CA; RA CD40/TYK2 — see
`docs/mcp-eval-plan.md` §7-5, held-out reproduced 7/8 diseases). It **does not
add an OT ranking bonus** — the sort/filter stays pure `spec_adj`+artifact after
the candidate pool is expanded. **Framing rule for later phases: these are
OpenTargets DB scores, not literature evidence** — mention them only as
"OpenTargets also reports genetic/clinical evidence for this gene," never cite
them as a paper, never feed them to `verify_citations.py`, and never conflate
them with the abstract-grounded summary.

## Phase 1 — why spec_adj is two axes, and what it does not prove

**Read spec_adj and co_papers as two axes, not one hard cut.** `spec_adj` is
keyword *specificity*, not keyword *relatedness*. A pleiotropic hub gene truly
central to the keyword (IL4, STAT6, CD8A for atopy) has a huge total-paper
denominator, so its specificity is structurally suppressed and it sinks below the
cutoff — a false negative (measured: IL4 co=8409, overwhelming evidence, yet
spec_adj ~0.083, mid-low). And in the boundary band the `spec_adj` curve is
smooth (0.018 → 0.008 with no elbow), so a single hard threshold has no natural
place to fall — it will always clip a legitimate near-miss (e.g. a known keyword
miRNA landing just under 0.015). So don't report one thresholded list as the
whole answer: read `genes_all_scored.tsv` on both axes and label two zones —
**core/specific** (high `spec_adj`) and **related-but-pleiotropic** (high
`co_papers`, low `spec_adj`). A relative-percentile floor is not the fix — it was
already dropped for demoting niche core genes; keep the absolute floor and add
the co-axis read on top.

**spec_adj measures *studied-together*, not *proven association*.**
Co-occurrence counts a gene+keyword paper regardless of polarity: a paper
reporting **no** association, or using the gene as a control, still counts. So
read the ranked list as a **lead set to verify against the abstracts**, never as
a causal/association claim on its own. This is why the evidence PMIDs and Phase
2–4 abstract check exist — the statistic ranks, the abstracts adjudicate.

## Phase 3 — subagent token model (measured 2026-07-09)

Per-agent total ≈ `38,800 + 4,950·b` tokens (b = genes in the batch; fit error
<0.5% across b=1/5/15/30/45). So N genes over k agents cost
`k·38,800 + 4,950·N` — the per-gene term is split-invariant, and **only the agent
count k drives cost**. Minimize k (bigger batches) down to the quality/latency
limit. e.g. N=30 as 1×30 (187k) beats 3×10 (265k) by ~29%.

This is why the batch is capped at ≤30 genes/agent (not the agent count): each
spawned subagent costs a flat ~38.8k tokens regardless of batch, so fewer, fuller
agents save tokens. 30 is the sweet spot — token/gene has flattened by 30
(≈6.0k, within 2% of the b=45 floor) while staying well under sonnet's context
peak. Measured clean to b=45 (100% coverage, stable format); 30 is the
recommended cap, not the failure point.
