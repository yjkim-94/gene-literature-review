# gene-literature-review — Design Document

> Design validated through a loop (propose → critique → revise). Method: evaluator-optimizer / reflection loop
> (propose → critique against criteria → revise, stop when fatal flaws are gone).

## Purpose

The user gives a keyword (e.g. "atopy") and wants an **accurate, large list of related genes**.
Literature review is not for per-gene narrative summaries — it is the **evidence layer that validates list accuracy**.

- **List-centric**: specificity value + evidence PMID *is* the proof that "this gene is genuinely tied to the keyword."
- At large scale (hundreds–1000), do not run per-gene abstract fan-out summaries — impractical and unnecessary for list accuracy.
- Full per-gene literature summary (Phase 2–4) applies only to a small top-N, optionally.

## Settled decisions

1. **Drop the confidence label.** specificity is inherently a keyword-relative metric, so it can't be compared in absolute
   terms across keywords, and a fixed threshold (formerly 0.3/0.1) is off for every keyword. Instead of a label,
   expose the **raw fields (rank + specificity + co_papers)** and leave judgment to the user / audit agent.

2. **Compute specificity on an entity basis + statistical correction.** Align the identity basis of discovery
   (PubTator GeneID) and ranking (설계 C), and rank by **denominator floor + Wilson lower bound** rather than the point
   estimate (설계 D). The old `"<sym>"[tiab]` string matching and raw-ratio sort must be dropped.

---

## Design A — Keyword expansion (search problem)

The keyword is used in two places in the script, with asymmetric synonym handling:
- Candidate **discovery** via PubTator3 free-text search (no MeSH expansion)
- specificity **numerator** — formerly `"<gene>"[tiab] AND <keyword>` PubMed search (PubMed Automatic Term Mapping silently expands MeSH)

### Loop result (4 rounds, stopped when fatal flaws gone)

| Round | Plan | Fatal flaw | Fix direction |
|-------|------|------------|---------------|
| 1 | Input string verbatim (current) | "아토피" (Korean) → ~0 PubTator hits; "atopic dermatitis" missed in discovery → recall collapse | Expand to an English synonym set |
| 2 | LLM OR-expands synonyms | LLM-guessed abbreviations are a silent contamination source ("AD"→Alzheimer), invisible | Ground expansion in controlled vocab (MeSH) |
| 3 | Expand to MeSH entry terms, symmetric | Ambiguous input silently maps to the wrong MeSH (trait vs disease) | Confirm the expanded query + literal fallback |
| 4 | **Plan D (adopted)** | none | — |

### Adopted: Plan D — later superseded by Design F

User keyword → **resolve to a MeSH concept, expand to curated synonyms** →
**confirm the expanded query once** → apply symmetrically to both discovery and the specificity numerator →
record in the method section. Novel terms with no MeSH (cuproptosis, etc.) fall back to **literal** (an exact string with no synonym problem).

> **Superseded (Design F):** the "OR-expand curated synonyms" mechanism was replaced. Post-implementation measurement showed free-text synonyms are **not** auto-normalized and grouping-less OR **collapses** the PubTator parser (`atopic dermatitis OR atopic eczema` → 20,466, below the single term's 66,111). The PubTator **concept entity** (`@DISEASE_Dermatitis_Atopic`) unions synonyms natively in one exact call — see Design F. The MeSH-grounding + confirmation-gate insight below still holds; only the query mechanism changed.

**Insights**
1. The root of failure isn't lack of synonyms but the **asymmetric keyword handling across the two subsystems** — expanding only one side distorts specificity, so both must be expanded together.
2. The real danger of auto-expansion isn't recall but **silent contamination** (guessed abbreviations, mis-mapping) — blocked only by MeSH grounding + a confirmation gate, two layers.
3. Not a new feature but **moving the existing "confirm the gene list" gate one step earlier, to "confirm the query."**

---

## Design B — AI agent verification (preventing silent contamination)

Replace/reinforce Design A's confirmation gate with AI-agent verification that survives large / automated runs.
Core tension: **if the verifier itself hallucinates, it's worthless** → the question is where and on what basis to use the AI.

### Loop result (4 rounds, stopped when fatal flaws gone)

| Round | Plan | Fatal flaw | Fix direction |
|-------|------|------------|---------------|
| 1 | AI verifies the expanded term set | verifying terms isn't verifying the result gene list (contamination happens at the gene level) | Move to gene level, ground in evidence |
| 2 | Per-candidate AI verification (abstract-grounded) | passengers have real co-papers → judged "related," not filtered; cost explodes at 1000-scale | Don't use AI as a bulk filter — only on ambiguous cases |
| 3 | 2-tier: specificity bulk + AI on the boundary only | if concept resolution (a) is wrong, downstream gene audit (b) is meaningless (order dependency) | Harden (a) with grounding + cross-check, gate (b) |
| 4 | **Plan D (adopted)** | none (residual failures surface via human escalation) | — |

### Adopted: Plan D

specificity handles bulk ranking cheaply; **the AI agent is used only in 3 roles, not as a bulk filter**:

- **(a) Concept disambiguation** — give the agent the candidate MeSH concepts' **definitions and entry terms (fetched, not recalled)** plus a sample of top-gene evidence → return the best concept + confidence + reasoning.
- **(a') Cross-check** — verify the chosen concept's top-specificity genes fit its definition biologically.
- **(b) Boundary gene audit** — only after (a) is fixed; keep/drop borderline-specificity genes with abstract evidence + PMIDs, advisory / logged.
- **Escalation** — human intervention only when agent confidence is low or the cross-check conflicts (the one point worth interrupting for).

**Insights**
1. **Don't use AI as a bulk filter** — passengers have real co-papers, so a grounded AI answers "related" and does core/passenger
   discrimination worse than specificity while exploding cost. Per evaluator-optimizer orthodoxy, **spend the expensive evaluator only where the cheap heuristic is unreliable.**
2. **AI verification must be grounded** — self-knowledge judgment makes the verifier itself a contamination source. Reuse the "only PMIDs in the file" pattern (0-hallucination, proven in the Phase 3 fan-out).
3. **Order is safety** — if (a) is wrong, downstream (b) is meaningless, so hardening (a) with cross-check + low-confidence escalation is the bottleneck of the whole contamination defense.

---

## Design C — Gene identity basis alignment (found in subagent critique round 2, top-priority FATAL)

The root flaw loops A and B missed by focusing only on **keyword** expansion symmetry: **discovery is entity-based, ranking is string-based.**

- `rank_gene_ids`: counts PubTator NER **GeneIDs** — normalized entities.
- `resolve_human` (old): `"<sym>"[tiab]`, `"<sym>"[tiab] AND <keyword>` — **bare-symbol string** matching.

### FATAL flaws stemming from this root

| # | Flaw | Scenario | Root |
|---|------|----------|------|
| 1 | Common-word / short symbols poison specificity | `CAT` (catalase) matches "cat allergen" papers → top atopy gene. Same for `REST`/`SET`/`CAD`/`MARS`. Both numerator and denominator are noise | string matching |
| 2 | Unfielded keyword injection → ATM/MeSH explosion inflates only the numerator | "atopy" → `hypersensitivity[MeSH]` expansion, passengers IL6/TNF/STAT3 get numerator↑ → passengers promoted | numerator/denominator basis mismatch |
| 4 | "Representative PMID = evidence" can be non-evidential | `"CAT"[tiab] AND atopy` PMIDs may not mention the gene at all → a fabricated association presented as evidence (hallucination) | string matching |
| 6 | PubTator NER false positives contaminate the candidate pool | `SDS` (detergent) / `CD` / `ARM` tagged as genes → enter candidates | entity/string gap |

### Adopted fix (closes all four at once)

- **Compute specificity on PubTator entity co-occurrence**: `(GeneID ∧ keyword papers) / (GeneID papers)`.
  Aligns discovery and ranking on the same entity basis → flaws 1·4·6 vanish (mis-tagged tokens have no coherent gene-entity co-occurrence).
- **Match numerator/denominator basis**: field-restrict the keyword (`<keyword>[tiab]` or a confirmed MeSH descriptor)
  so only one side isn't ATM/MeSH-expanded → flaw 2 vanishes.
- **All representative PMIDs come from the entity-grounded query only** — string-query PMIDs are never used as evidence (flaw 4).

### Design B audit role redefined (critique round 1 flaw 3 + round 2 FATAL-2)

**The AI audit cannot be a relevance gate for the high-confidence band.** Per insight B.1, passengers have real co-abstracts
saying "gene X … keyword Y," so a grounded AI answers "related." The audit's **only real capability is lexical disambiguation**
("CAT is the animal here, not catalase") — for common-word / short symbols only.
→ AI audit scope: **limited to lexical disambiguation of common-word / short symbols.** High-band defense against irrelevant
genes is the **statistics' job (Design D)**, not the AI's.

### Design A synonym verification hardened (critique flaw 5)

Before an expansion term enters the numerator query, **assert each term is a verbatim member of the fetched MeSH entry-term list**,
drop and log otherwise. A mechanical check, not a judgment — blocks silent contamination from AI-guessed synonyms.

### Meta (critique flaw 7)

The loop's "no fatal flaw → stop" was **false confidence**: neither loop ever put the gene-symbol basis asymmetry in the critique
frame, so it certified safety it never tested. → Going forward, an **external (subagent) adversarial critique is a mandatory gate**
before the loop stops.

---

## Design D — Correcting the entity metric's own noise (found in critique round 2, FATAL)

The entity basis (Design C) caught string false-symbols but introduced **ratio noise**.

### FATAL

| # | Flaw | Scenario | Fix |
|---|------|----------|-----|
| D-1 | **small denominator → spec=1.0 promotes the least-studied gene to the top** | atopy: 3 papers total (all broad reviews name-dropping the gene once in a table) → spec=1.0 → ranks above FLG (~0.3–0.5). `min_co=5` can't stop it (5/5=1.0) | statistical correction below |
| D-2 | **high-band AI audit is theater** (see Design B redefinition) | a normally-named low-denominator artifact matches neither audit suspect class (common-word · spec-spike), so it's never audited | move defense AI→statistics |

### Adopted fix

- **Denominator floor (low absolute, ~10)**: a high absolute floor (30–50) is forbidden — cuproptosis core genes have 10–25 papers
  total and would be dropped wholesale (critique round 3 NON-FATAL-1). **The relative-percentile floor was also dropped** — post-implementation
  measurement showed FDX1 (1565 papers, spec 0.66, the best core gene) demoted to rank 6 just for having fewer papers than its sibling
  core genes (2000–3700). A percentile penalizes the "less-studied but specific" best gene.
  → Settled on a **low absolute floor (only n<10 demoted as artifacts, not deleted)**: real 3/3 artifacts sink, while cuproptosis
  niche core (10–25 papers) and FDX1 stay. The lower bound handles the rest of the ordering.
- **Rank by lower confidence bound, not the point estimate**: sort by the proportion's **Wilson/Jeffreys lower bound**.
  spec=1.0@n=3 → ~0.4 (collapses), spec=0.7@n=200 → ~0.7 (held) = the ordering we want. One line of arithmetic.
- High-band defense is the statistics' job; the AI audit is limited to lexical disambiguation (Design B).

### Basis contradiction resolved (critique round 2 NON-FATAL-3)

Design C mixed "entity co-occurrence" and "keyword `[tiab]` restriction," **re-creating the round-1 basis asymmetry, flipped**.
If denominator = PubTator GeneID papers but numerator = `keyword[tiab]` matches, a core gene whose papers carry the keyword only as
a **MeSH tag** loses numerator mass → the real gene falls below min_spec (recall hole).
→ **Unify on one basis**: measure keyword co-occurrence as a **concept/MeSH co-tag on the same PubTator annotated corpus** as the
denominator. Never mix a PubTator denominator with a `[tiab]` numerator.

### Numerator inflation mitigation (critique round 2 NON-FATAL-4)

PubTator counts a co-occurrence whether the gene is the subject or a single mention in a 60-gene table. One broad review grants
every listed gene +1 → worsens D-1 for low-denominator genes. → Require **same-passage co-occurrence**, or down-weight/cap papers with
very high gene-annotation counts. The lower bound (D-1) absorbs most of it.

### Hallucination path — confirmed closed (invariant)

The pipeline has **no generative source of gene identity**: symbols come from PubTator NER GeneID → NCBI esummary, PMIDs only from
entity-grounded queries. AI roles (concept resolution · cross-check · audit) are **strictly subtractive/advisory and never emit a gene
symbol**. → Single invariant to enforce in code review: **the AI never names a gene.**

---

## Design E — Adopting the residual NON-FATALs (critique round 3, loop stop)

Round 3 verdict: **0 FATAL, loop stops.** Both hallucination and irrelevant genes are defended by design. Residual corrections adopted below.

- **Relative floor → low absolute floor** (NON-FATAL-1): reflected in Design D. The Wilson lower bound alone is insufficient
  (5/5@n=5 ≈ 0.57, still beats FLG ~0.4), so the floor has a real role — but as a low absolute value + demotion, not a percentile.
- **Hard gate for high-band lexical mistags** (NON-FATAL-2): run the AI lexical audit on **high-band common-word / short symbols too**,
  not just the boundary, and make a **confirmed mistag a hard drop, not advisory.** Design C's empirical claim that "entity co-occurrence
  eliminates mis-tags" should be **validated once against a known common-word symbol set before certifying it.**
- **No concept self-confidence in automated mode** (NON-FATAL-3): ambiguous / short keywords ("AD") map wrong at **high confidence**
  due to dominant-sense bias, so concept selection **requires human confirmation** — no AI self-confidence auto-approve.
- **Prefer down-weighting for numerator inflation** (NON-FATAL-4): "require same-passage" makes only the numerator passage-scoped,
  reintroducing basis asymmetry → prefer **down-weighting large gene-list papers** (keeps the document-level basis).

**Implementation lagged the design**: `fetch_genes.py` still had the pre-round-2 string / `[tiab]` + raw-ratio logic. Designs C/D/E
mandate replacing it. (This has since been implemented — see the scripts and README.)

---

## Design F — Concept entity replaces OR-expansion (measurement-driven revision)

Design A's adopted Plan D OR-expanded a MeSH concept's curated entry terms into `--keyword`. Post-implementation measurement falsified its premise.

### Measured facts (PubTator3, atopic dermatitis)

| Query | count | note |
|-------|-------|------|
| `atopic dermatitis` | 66,111 | dominant single term |
| `atopic eczema` | 20,397 | different count, top-page PMIDs **0/10** overlap with AD → distinct papers |
| `atopic dermatitis OR atopic eczema` | 20,466 | **collapses below the single term** — OR is not a union |
| `"@DISEASE_Dermatitis_Atopic"` (entity) | 64,349 | synonym-union universe, one call |
| `"@GENE_2312" AND "@DISEASE_Dermatitis_Atopic"` | 3,397 | FLG entity co-occurrence (vs 3,349 free-text) |

Two findings overturn Plan D: (1) free-text synonyms are **not** auto-normalized (each matches a different set), so a single term under-covers; (2) grouping-less OR **collapses the PubTator parser** (mis-scopes the `AND`), so it can never union. The earlier "single canonical term is highest-recall" claim (an interim PROBLEM.md note) was also only half-right.

### Adopted: PubTator concept entity as the keyword side

- Resolve the keyword to a **PubTator concept entity** (`@DISEASE_Dermatitis_Atopic`), passed as `--entity`. Both discovery and the specificity numerator become `"@GENE_<id>" AND "<entity>"` (each token **quoted** — the unquoted `:` in `@DISEASE_MESH:D…` 400s). The entity **unions the concept's surface synonyms natively** in one exact call — no OR, no parser fragility.
- **Objective concept selection**: `entity_candidates()` (`--resolve` mode) fetches PubTator autocomplete candidates + each one's paper count, so the concept is chosen by **evidence volume, not the AI's dominant-sense guess** — this mechanizes the round-3 NON-FATAL-3 "no concept self-confidence" rule (autocomplete = objective, `[]` ⇒ novel term ⇒ free-text fallback).
- Novel terms with no entity (cuproptosis) omit `--entity` → free-text `--keyword`, unchanged.

**Insight**: the two-subsystem symmetry (Design A insight 1) is preserved — the entity is applied to *both* discovery and numerator. What changed is the vehicle: an **entity** (normalized, exact) instead of an **OR string** (fragile, non-normalizing). The MeSH-grounding + confirmation gate (Design A/B) still stands.

### Implementation deltas adopted alongside Design F (same iteration)

- **`spec_lower` → `spec_adj`** column rename (readability; "confidence-adjusted specificity"). Same Wilson-lower-bound semantics.
- **Run directory** `output/<slug>/`: every artifact of one run co-located; `slug()` is the single source of truth (empty-slug → `kw-<md5>` fallback so non-ASCII keywords don't collide).
- **Scoring bounded at `SCORE_MULTIPLE(4) × --max`** by co-mention, with **organism filtered first** (cheap batched esummary) before the 2-call scoring — replaces the manual `--cand-pool`. Co-mention prefilter doubles as an artifact cut.
- **Preflight** (entity `count` → scan-time estimate → `--scan`/`--organism` confirmation) before running; **pre-filter sidecar** `genes_all_scored.tsv` for data-driven cutoffs; **two-axis read** (`spec_adj` × `co_papers`) to surface pleiotropic hub genes the specificity cut buries.
- **Fixed user-facing output blocks** per checkpoint (SKILL.md) for run-to-run consistency.
- Validated by an external Codex adversarial pass (Design C meta rule): 2 FATAL found (empty-slug collapse, `--resolve` malformed-JSON crash) → fixed → 0 FATAL remaining.

## Open (non-fatal, absorbed by human escalation)

- Ranking quality of the default top MeSH concept.
- Borderline band width setting (candidate from the gap/knee of the specificity distribution).
- Default include/exclude for **genuinely gene-sharing adjacent concepts** (e.g. the atopic triad).

## Implementation touchpoints

- `fetch_genes.py` specificity + ranking — **top priority**: drop string specificity + raw-ratio sort → PubTator entity co-occurrence
  (Design C) + denominator floor + lower-bound sort (Design D). Numerator/denominator on the same corpus.
- `fetch_genes.py` keyword injection — **concept entity (`--entity`) applied symmetrically to both sides** (Design F; replaced the OR-expanded synonym set), unified basis (PubTator concept co-occurrence).
- confidence label dropped, raw fields exposed.
- Representative PMIDs — from the entity-grounded query only.
- Numerator computation — require same-passage co-occurrence or down-weight large gene-list papers.
- `SKILL.md` Phase 1 — "confirm query" gate + AI concept resolution/cross-check + objective entity resolution (`--resolve`, replaced synonym verbatim assert).
  The AI audit is **limited to lexical disambiguation of common-word / short symbols** (not a relevance gate). Invariant: the AI never names a gene.
- Retraction filter (separate discussion) — exclude/mark `Retracted Publication` via the efetch publication-type tag.
