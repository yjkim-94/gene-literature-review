---
name: gene-literature-review
description: Use when a user gives a biological keyword (disease, pathway, phenotype, biological process, drug mechanism) and wants the associated genes AND a per-gene literature summary -- including gene-discovery phrasings without the word "literature" ("X에 관여하는 유전자 뭐가 있어", "what genes are involved in Y"). ALSO use when the user already has a gene list and wants each gene's PubMed literature summarized. Do NOT use for summarizing a single paper/PDF the user provides, for a general literature review not organized per-gene, or for pure sequence/variant/expression lookups with no literature component.
---

# Gene Literature Review

Given a keyword (or a user-supplied gene list), proceed in order: **① related gene list → ② collect each gene's PubMed literature → ③ per-gene summary → ④ integrated document.**

**Two entry modes — route first (both are first-class, not fallbacks):**
- **Mode A · keyword given** ("X에 관여하는 유전자", "review genes in X"): Phase 1 discovers and ranks genes from the keyword (with `--ot-overlay` for disease keywords), then 2 → 3 → 4.
- **Mode B · gene list given** ("이 유전자들 문헌 정리해줘: GENE1, GENE2, GENE3"): **skip Phase 1 discovery/ranking**. Write the user's symbols to `output/manual/genes.tsv` (single `symbol` column, header row), then 2 → 3 → 4. Keyword handling: if the user also names a disease/keyword context, pass it as `--keyword` in Phase 2 for keyword-specific papers; with no context, omit `--keyword` for **general per-gene literature** and use the `핵심 문헌 요지` label in Phase 3. The confirmation gate (Phase 2) and citation verify (Phase 4) apply identically. OT overlay is a Mode-A feature only (it needs keyword→disease resolution and a discovered candidate pool), so Mode B produces no OT columns/section.

### Run directory (artifact naming — one place, everything chains off it)

Every artifact of a single run lives under one **run directory** `output/<slug>/`, where `<slug>` is the confirmed keyword as lowercase kebab-case (`atopic dermatitis` → `atopic-dermatitis`). Fixed layout, so separate keywords never overwrite each other and each step finds its input by location:

```
output/<slug>/
  run_config.json               # Phase 1 CLI options used (self-documenting run)
  phase1_fetch_genes.log        # Phase 1 progress log (A+B format, live, tail -f)
  genes.tsv                     # Phase 1 ranked list
  genes_all_scored.tsv          # Phase 1 pre-filter sidecar (auto)
  phase2_fetch_pubmed.log       # Phase 2 progress log (A+B format, live)
  lit/<SYMBOL>.json             # Phase 2 abstracts, one file per gene
  gene_literature_review.md     # Phase 4 final document
```

The slug is computed **once**, by `fetch_genes.py` from `--keyword`; downstream scripts derive their paths from the run dir (`fetch_pubmed.py` writes `lit/` next to `--genes`), so pass paths that stay inside `output/<slug>/` and never re-slug by hand. A user-supplied gene list (no keyword) has no slug — use `output/manual/` as the run dir.

## Design principles (why it works this way)

Two invariants drive every phase: **(1)** a script fetches abstract text into files, never the LLM (no token blow-up); **(2)** every claim cites a real PMID that `verify_citations.py` mechanically re-checks (no hallucination). Rationale, access/retracted labels, and the full derivation: [`docs/method-rationale.md`](docs/method-rationale.md).

## User-facing output format (each block fixed — same every session)

Each checkpoint uses the block defined for **that phase** below: a `■ Phase N · <단계>` header, aligned `라벨 : 값` lines, and an optional `⚠` / `→` line. **Put a blank line between logical groups** (header ↔ 값 ↔ caveat/prompt) so each block breathes. Fill the blanks; keep each phase's own structure, labels, and order identical across sessions (cross-session consistency is the point — the phases are *not* required to match one another). Labels stay Korean; machine tokens (paths, `spec_adj`, `--max`) stay literal. These fire **one at a time** across the run (never stacked), separated by the user's replies.

**Decision points (blocks ending in a `→` prompt that asks the user to choose or confirm) → use the `AskUserQuestion` tool.** Show the `■` block first as the context, then raise the actual choice through `AskUserQuestion` so the options are clickable (e.g. Query gate: the canonical/concept candidates; Phase 4: `.docx` 변환 여부). If `AskUserQuestion` is unavailable, fall back to the plain block — but in that case **spell out the alternatives** on/after the `→` line (which other concept candidates exist, yes/no, etc.), never just an open-ended "진행할까요?". Info-only blocks (Preflight, Scan 완료, 문헌 수집·요약·통합 완료) are not decision points — print them as-is.

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

→ 상위 <5×max>개(=5×max) scoring 시작
```

```
■ Phase 1 · 결과

scored : <scored>개 → 필터 통과 <통과수>개
저장   : output/<slug>/genes.tsv
전량   : genes_all_scored.tsv

[core/특이]         상위 <a>개  (high spec_adj)
[관련-pleiotropic]  별도 <b>개  (high co_papers, low spec_adj)

→ Phase 2는 아직 진행하지 않습니다. gene 목록을 확인한 뒤 승인해 주세요.
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

저장     : output/<slug>/gene_literature_review.md
gene     : <N>개 · 근거 논문 <총합>편
인용검증 : verify_citations orphan <n>편

→ .docx 변환할까요? (md-to-docx)
```

Large-request / list-centric mode ends at the `Phase 1 · 결과` block (Phases 2–4 skipped) — say so on that block instead of showing the later ones.

## Phase 1 — Obtain the gene list

**First, route by request type:**

- **User supplied a gene list directly** ("do a literature review on geneA, geneB, geneC"): skip this phase. Write the given symbols into a one-column TSV with a `symbol` header at `output/manual/genes.tsv` and go to Phase 2. If there is no keyword, omit `--keyword` in fetch_pubmed to get **general gene literature** (representative papers for the gene itself, not keyword-specific association).
- **Keyword only** ("summarize genes related to atopy"): proceed below.
- **Large request (hundreds–1000)** ("1000 genes for atopy"): **list-centric mode** — see "Large requests" below.

```bash
python scripts/fetch_genes.py --keyword "atopic dermatitis" --entity "@DISEASE_Dermatitis_Atopic" --organism human --max 20 --ot-overlay
# --entity (token from `--resolve`) unions the concept's synonyms.
# --ot-overlay is passed by default for disease keywords (see below); it is a no-op for non-disease terms.
# writes output/<slug>/genes.tsv (+ genes_all_scored.tsv). --out overrides.
```

`fetch_genes.py` picks genes in two steps. ① Use **PubTator3** to collect NER-tagged gene candidates from the concept's papers — free-text NCBI Gene search only pushes generic hub genes (TP53/EGFR/APOE) to the top. ② Rerank candidates by **entity-based specificity**:

```
specificity = (papers where the gene ENTITY co-occurs with the keyword/concept) / (papers with the gene entity)
```

Both counts come from PubTator `@GENE_<id>` search — **not `[tiab]` string matching** (so `CAT`→catalase entity, not "cat allergen"). **When `--entity @DISEASE_MESH:<id>` is passed** (from the gate), both discovery and numerator become `"@GENE_<id>" AND "@DISEASE_MESH:<id>"`, which unions the concept's surface synonyms natively. **Do NOT OR-expand synonyms into `--keyword`** — grouping-less OR collapses the PubTator parser; the entity is the only correct union. Novel terms with no MeSH (cuproptosis) omit `--entity` and fall back to free-text `--keyword`.

Ranking uses the **Wilson lower bound (`spec_adj`), not the point estimate**; a **low absolute denominator floor** demotes (not deletes) genes with total papers below `--min-gene-papers`; and immunoglobulin/TCR/HLA **structural-artifact** symbols (e.g. IGHE) have their sort score halved (0.5×, demoted not deleted). *Why each of these — measured numbers, the dropped relative-percentile floor, the OR-collapse counts:* [`docs/method-rationale.md`](docs/method-rationale.md).

Output is a **tab-separated TSV** (opens directly in Excel) with columns `symbol · gene_id · name · co_papers · gene_papers · specificity · spec_adj · below_floor · artifact · evidence_pmids · ot_genetic · ot_clinical` (evidence_pmids is `;`-joined; `ot_genetic`/`ot_clinical` are empty unless `--ot-overlay`, see below), sorted by `spec_adj` descending (with the artifact demotion applied to the sort score). Default thresholds: `--min-specificity 0.05` (applied to the lower bound), `--min-co 5`, `--min-gene-papers 10`.

**Scoring is bounded by `--max`, not by scan size.** Specificity scoring costs 2 PubTator calls per candidate (the dominant cost), so only the **top `5 × --max` PubTator scan candidates by co-mention** get scored (`SCORE_MULTIPLE` in the script). Organism is filtered *first*, on the cheap batched esummary, so the 2-call scoring never runs on a non-`--organism` gene. For disease keywords with `--ot-overlay`, every OpenTargets target with `genetic_association > 0` or `clinical > 0` is also exact-mapped from OT approved symbol to NCBI Gene ID and appended as an **OT rescue candidate** outside that cap, then scored by the same PubTator `@GENE` numerator/denominator. The `4×` headroom over the final `--max` absorbs filter + organism dropout so `--max` genes still survive; fewer come back if the keyword has fewer specific genes (never inflated — see [`docs/method-rationale.md`](docs/method-rationale.md)). There is **no `--cand-pool`** (removed; now derived from `--max`).

Alongside `genes.tsv`, the script always writes a sidecar `genes_all_scored.tsv` — **every scored candidate before the `min_co`/`min_specificity` filter**, same columns, sorted by `spec_adj`. Read it to set the cutoff from the actual `spec_adj` distribution (does 0.05 land on a real gap, or slice through a smooth run?) and to see exactly which gene was the first one cut and by how much — the filtered `genes.tsv` alone can't show that.

`evidence_pmids` are representative PMIDs **from the entity co-occurrence query only** — string-query PMIDs may not mention the gene at all, so they are never used as evidence.

**OpenTargets overlay (`--ot-overlay`) — the skill passes it by default.** For disease keywords the workflow always runs Phase 1 with `--ot-overlay`. (The CLI flag itself defaults **off** so evals/tests run pure-literature — do not rely on the script default; the human-facing skill run is what turns it on.) It adds two columns — `ot_genetic` (OpenTargets `genetic_association` score) and `ot_clinical` (`clinical`/known-drug score) — as a **DB cross-reference**, for disease keywords only (it resolves the keyword to an EFO/MONDO id; non-disease terms like `ferroptosis` and any network/lookup miss leave the columns empty, and the run never fails). It also uses all OT targets with `ot_genetic > 0` or `ot_clinical > 0` as rescue candidates: OT approved symbols are exact-mapped to human NCBI Gene IDs, added to `genes_all_scored.tsv`, and scored by the same PubTator specificity logic. **OT rescue is human-only** — OpenTargets symbols are human (uppercase `IL7R`), so a non-human `--organism` (e.g. mouse `Il7r`) matches zero OT targets and the rescue/columns come back empty; the script logs a warning rather than failing silently. It **does not add an OT ranking bonus** — the sort/filter is still pure `spec_adj`+artifact after the candidate pool is expanded. It also writes `output/<slug>/ot_scores.tsv` (the full OT genetic/clinical target list for that disease), which Phase 4 uses for the complement callout. Its value is *complementary*, not a replacement — surfacing genetic/clinically-drugged targets co-occurrence misses (why, with held-out numbers: [`docs/method-rationale.md`](docs/method-rationale.md)). **Framing rule for later phases: these are OpenTargets DB scores, not literature evidence** — mention them only as "OpenTargets also reports genetic/clinical evidence for this gene," never cite them as a paper, never feed them to `verify_citations.py`, and never conflate them with the abstract-grounded summary.

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
5. After the scan, **report the candidate gene count** ("N gene candidates found") and proceed to scoring without a second gate — scoring volume is already bounded at `5 × --max`.

### Result review + AI audit (optional, at scale)

Read the result file, show the `Phase 1 · 결과` block, and **confirm the gene list with the user first**. Make the waiting state explicit: Phase 2 has not started, and it will start only after the user approves the gene list. When the list is too large to review by hand, use an AI audit but **keep it narrow**:

- The AI audit is **not a relevance gate.** Passengers have real co-abstracts, so a grounded AI answers "related" for them too; core/passenger discrimination is the statistics' job (spec_adj · floor).
- The AI audit's only role is **lexical disambiguation of common-word / short symbols** ("is CAT catalase or the animal here?"). Check such symbols in the high-confidence band and **hard-drop confirmed mistags**.
- **Invariant: the AI never names a gene.** All symbols come only from PubTator NER → esummary. The AI's roles are subtractive (drop) and disambiguation only.

**Read spec_adj and co_papers as two axes, not one hard cut.** `spec_adj` is keyword *specificity*, not *relatedness* — a pleiotropic hub gene central to the keyword (IL4, STAT6, CD8A) has a huge denominator and sinks below the cutoff (false negative), and the boundary band is smooth (no natural elbow). So don't report one thresholded list as the whole answer: read `genes_all_scored.tsv` on both axes and label **two zones** — **core/specific** (high `spec_adj`) and **related-but-pleiotropic** (high `co_papers`, low `spec_adj`), surfacing the second zone's high-`co` genes explicitly. *Measured examples (IL4 co=8409/spec_adj~0.083, the smooth 0.018→0.008 band):* [`docs/method-rationale.md`](docs/method-rationale.md).

**Caveat — `spec_adj` measures *studied-together*, not *proven association*.** Co-occurrence counts a gene+keyword paper regardless of polarity: a paper reporting **no** association, or using the gene as a control, still counts. So read the ranked list as a **lead set to verify against the abstracts**, never as a causal/association claim on its own. This is why the evidence PMIDs and Phase 2–4 abstract check exist — the statistic ranks, the abstracts adjudicate.

### Large requests (hundreds–1000): list-centric mode

For hundreds–1000 genes, skip per-gene literature summaries — collecting and summarizing 1000 abstracts is impractical and unnecessary for list accuracy. **The Phase 1 TSV (ranking · specificity · evidence PMIDs) is the final deliverable**; skip Phases 2–3 (optionally apply them only to a top-N).

- Scale up `--scan` and `--max`. Scoring volume is `5 × --max` (no `--cand-pool` anymore), so `--max 1000` scores up to ~5,000 candidates automatically. Raise `--scan` well above `--max` (e.g. `--scan 3000` for `--max 1000`) so the candidate pool is deep enough to fill the target. PubTator makes 2 calls per scored candidate, so thousands take tens of minutes to hours — quote the estimate up front.
- Relax filters: at scale, recall comes first, so lower `--min-specificity` / `--min-co` to pass more through. The `spec_adj` sort still holds, so the top stays specific.
- **Realistic ceiling**: a keyword may not have 1000 truly specific genes. Return only as many as pass, and tell the user that count (don't inflate it).

## Phase 2 — Literature collection (script writes to files)

Collect abstracts for the confirmed gene list. **Do not read abstract text in this phase** — the script writes to files only.

**Confirmation gate (enforced by the script, fail-closed).** Phase 2 will not run until the gene list is human-confirmed. After the user approves the list at the `Phase 1 · 결과` checkpoint, record that approval by writing `OK` into `output/<slug>/genes.confirmed`, *then* run the collector. `fetch_pubmed.py` hard-stops (exit) if that file is missing or lacks `OK`, so an un-reviewed list can never silently flow into collection — the default state is "stop." Do not write the file before the user has actually confirmed.

```bash
echo OK > output/<slug>/genes.confirmed    # only after the user confirms the Phase 1 list
python scripts/fetch_pubmed.py --genes output/<slug>/genes.tsv --keyword "<keyword>" \
  --entity "@DISEASE_MESH:D003876" --per-gene 5
# writes output/<slug>/lit/ by default (next to --genes). --out-dir overrides.
```

**Pass the same `--entity` token used in Phase 1** (the confirmed disease entity). With it, each gene's papers are searched by PubTator entity (`"@GENE_<gene_id>" AND "<entity>"`) — the same NER-scoped query Phase 1 used, so a common-word symbol (`CAT`→catalase) can't pull in string-collision papers. Requires each gene row to carry its `gene_id` (always present in Mode-A `genes.tsv`). **Omit `--entity`** for Mode B (user-supplied list) or novel terms with no MeSH entity — the script then falls back to free-text `esearch` (`<symbol> AND <keyword>`, or `<symbol>` alone when `--keyword` is also omitted). Per gene, the `entity`/`string` path taken is printed in the log. Abstract text, `access`, and `retracted` are always filled by E-utilities `efetch` regardless of which search path chose the PMIDs.

Produces `output/<slug>/lit/<symbol>.json` per gene. Each paper record:

```json
{"pmid": "12345678", "url": "https://pubmed.ncbi.nlm.nih.gov/12345678/",
 "title": "...", "abstract": "...", "year": 2021,
 "journal": "...", "access": "full-text" | "abstract-only",
 "pmcid": "PMC..." | null, "retracted": true | false}
```

`access` is `full-text` when a PMC open-access full text **exists**, else `abstract-only` — this marks whether a free full text is *available*; the abstract is what gets summarized either way. `url` is the ready-made PubMed link (so the summary step never reconstructs it). `retracted` is `true` for papers PubMed tags `Retracted Publication` (MeSH D016441) — flag these and drop them from the evidence. Only the top `--per-gene` papers (by relevance) are fetched per gene to bound scale.

## Phase 3 — Per-gene summary (identical template)

Summarize each gene from its `output/<slug>/lit/<symbol>.json`. **Apply the exact same procedure and format to every gene** — varying depth or format per gene makes the integrated document uneven.

### 9 or fewer genes: sequential in the main context

Read one gene file at a time and summarize with the template below. After processing a gene, do not reference its raw text again.

### 10 or more genes: subagent fan-out (even batch split)

Set the batch size and subagent count from the gene count `N`:

- **Fix the batch at ≤30 genes/agent; agents = ⌈N / 30⌉, cap 8 concurrent.** Cap the *batch*, not the agent count — fewer, fuller agents cost less (each spawn is a flat ~38.8k tokens; 30 is the sweet spot). Derivation: [`docs/method-rationale.md`](docs/method-rationale.md).
- Split genes **as evenly as possible** into batches, one per agent (each ≤30). Distribute the remainder one at a time from the first batch.
  - e.g. 10 → 1[10] · 30 → 1[30] · 31 → 2[16/15] · 45 → 2[23/22] · 60 → 2[30/30] · 90 → 3[30×3] · 100 → 4[25×4]
- **If ⌈N/30⌉ > 8** (N > 240), run 8 agents concurrently and queue the rest into freed slots (waves) — but at that size it's really a large request, so prefer Phase 1 list-centric mode instead.
- Each subagent's **model is sonnet** — reading a file and filling a fixed template is a bounded task, matching cost, speed, and citation discipline. Measured clean to b=45; 30 is the recommended cap, not the failure point.

**Cost is driven by the agent count k, not the split** (`k·38,800 + 4,950·N` tokens) — so minimize k with bigger batches. Full measured token model: [`docs/method-rationale.md`](docs/method-rationale.md).

Each agent reads only its batch's gene files, burning the abstract tokens in the subagent context and returning only summaries to the main context. **Give every subagent the exact same prompt verbatim** (substituting each `<SYMBOL>` in the batch) — any drift in instructions splits the output format across genes.

Before spawning subagents, generate the batch artifacts from the confirmed `genes.tsv`; do not hand-copy gene lists into prompts:

```bash
python scripts/make_phase3_batches.py --genes output/<slug>/genes.tsv
# Mode B with no keyword/context:
python scripts/make_phase3_batches.py --genes output/<slug>/genes.tsv --general-literature
```

This writes `output/<slug>/phase3_batches/batchNN.symbols.txt` and `batchNN.prompt.txt`. `genes.tsv` remains the source of truth; the batch files are derived artifacts and may be deleted/rebuilt. The script uses the same even split rule above (`ceil(N/30)`, remainder distributed from the first batch) and removes stale `batch*.symbols.txt` / `batch*.prompt.txt` files in that output dir before rewriting.

Spawn each subagent with only the corresponding `batchNN.prompt.txt` (and `batchNN.symbols.txt` as a quick audit list). For N > 240, run only 8 prompt files concurrently and queue later files as waves. The main context should keep only the batch file paths and returned summaries, not the raw per-gene abstracts.

The output labels in the prompt below are the user-facing document and stay Korean:

```
Read output/<slug>/lit/<SYMBOL>.json only. Do not fetch anything.
Summarize gene <SYMBOL> using ONLY the abstracts in that file, following this exact template:

### <SYMBOL> — <full gene name>
- **키워드와의 연관성**: 2-3 sentences. End each claim with its evidence PMID in [PMID:xxxxxxxx] format.
- **주요 발견**: 2-4 bullets. Every bullet must cite a PMID.
- **근거 논문**: table | PMID | 연도 | 접근수준 | 한 줄 요지 | — for the PMID cell, use the file's "url" to build a clickable link [xxxxxxxx](https://pubmed.ncbi.nlm.nih.gov/xxxxxxxx/).
- **근거 논문 전체 보기**: @@PMIDLINK@@   ← output this literal token verbatim (Phase 4's add_pmid_links.py performs the substitution).

Rules:
- Cite ONLY PMIDs that exist in the file. Never invent a PMID or a finding.
- If a paper's "retracted" is true, mark ⚠철회 in its 접근수준 cell and do NOT use it in 연관성/주요 발견 (drop it as evidence).
- If a claim is from an abstract-only paper, that is fine — the access column records it.
- If the file has no papers, write "관련 문헌 없음" and stop.
Return only the filled template, nothing else.
```

If a batch has 2 or more genes, instruct the agent to apply the prompt above to each SYMBOL in the batch — read each gene file one by one, fill the template block per gene, and return them concatenated in order.

**When there is no keyword** (user supplied only a gene list): change the first item's label from `키워드와의 연관성` to **`핵심 문헌 요지`** and summarize the gene's own representative research. All other formatting and PMID citation rules are identical.

## Phase 4 — Integrated document

Assemble the per-gene summaries into a final document. **Save it as `output/<slug>/gene_literature_review.md`** (fixed filename, inside the run dir next to `genes.tsv`/`lit/`) unless the user names another path. Use the deterministic integration script first; do not hand-assemble the document unless the script is missing or fails:

```bash
python scripts/integrate_review.py --run-dir output/<slug> --keyword "<keyword>" --organism <organism>
```

The script reads `genes.tsv`, `summaries/batch*.md`, `lit/*.json`, and optional `ot_scores.tsv`; it writes the summary table, per-gene details, OpenTargets cross-reference, and method section. Always use this structure (the document is user-facing, so its headings stay Korean):

```markdown
# <keyword> 관련 Gene 문헌 조사

## 요약 (한눈에 보기)
| Gene | 키워드 연관성 (한 줄) | 근거 논문 수 | 최신 연도 | OT유전 | OT임상 |
|------|----------------------|-------------|----------|--------|--------|
> OT유전·OT임상 = OpenTargets DB 점수(문헌 근거 아님, 참고용). 값은 genes.tsv의 ot_genetic·ot_clinical, 없으면 –.

## Gene별 상세
<Phase 3의 gene별 요약을 그대로 이어붙임>

## OpenTargets 교차참조 (문헌 근거 아님)
> OpenTargets DB가 유전/임상 근거로 지목하지만 위 문헌 상위 목록엔 없는 타깃. **문헌 미검증**, DB 점수일 뿐 — 논문 인용·요약과 혼동 금지. 후속 조사 lead로만.

| Gene | OT유전 | OT임상 |
|------|--------|--------|
<scripts/ot_complement.py 출력을 그대로 렌더>

## 방법
- Gene 목록: NCBI Gene, keyword="<keyword>", organism=<...>, N=<...>
- 문헌: PubMed E-utilities, gene당 상위 <per-gene>편, 수집일 <YYYY-MM-DD>
- 접근수준: full-text=PMC 무료 전문 이용 가능(요약은 abstract 기준), abstract-only=abstract만 공개
- 철회 논문: PubMed가 Retracted Publication으로 표시한 논문은 ⚠철회로 표기하고 근거에서 제외
- OpenTargets 오버레이: genetic/clinical 점수는 DB 교차참조(문헌 아님), 랭킹 미반영
- 인용 검증: verify_citations.py로 인용된 모든 PMID가 수집 파일에 실재함을 기계 대조(orphan 0)
- 주의: spec_adj(특이도)는 "그 병 맥락에서 얼마나 연구됐는가"의 지표로 동시 등장(부정·무관 결과 포함)을 셈 — 인과·연관의 증명이 아니며 최종 판단은 근거 abstract 확인 필요
```

**OpenTargets overlay rendering (disease keywords).** `integrate_review.py` already does both of the following when `ot_scores.tsv` is present — this block is the spec it implements and the manual fallback if you must hand-assemble. Phase 1 ran with `--ot-overlay`, so: (1) fill the two OT columns in the 요약 table from `genes.tsv` (`ot_genetic`/`ot_clinical`; empty → `–`), and (2) build the `## OpenTargets 교차참조` section from the helper — it deterministically selects OT-flagged targets absent from the literature top-N (LLM must not hand-pick these):

```bash
python scripts/ot_complement.py --ot-scores output/<slug>/ot_scores.tsv --final output/<slug>/genes.tsv
```

Render its rows verbatim into the 교차참조 table. **Gating — if `ot_scores.tsv` is absent or the helper returns only a header** (non-disease keyword, or OT surfaced nothing beyond the literature list), **drop both the OT columns and the entire 교차참조 section**; the document is then byte-identical to a pure-literature run. These OT symbols are DB pointers only: never cite them as a PMID, never pass them to `verify_citations.py`, never merge them into per-gene summaries.

After saving, **verify citations mechanically** before offering the doc as final:

Fill the deterministic PubMed 전체보기 links (replaces @@PMIDLINK@@) before verifying:

```bash
python scripts/add_pmid_links.py --review output/<slug>/gene_literature_review.md
python scripts/verify_citations.py --review output/<slug>/gene_literature_review.md
# exit 0 = every cited PMID exists in its gene's lit/*.json; exit 1 lists orphans.
```

If it reports any orphan citation, re-summarize the offending gene (the summary cited a PMID not in the collected file) and re-run until orphan = 0. Then, if the user wants it, offer `.docx` conversion via the `md-to-docx` skill.

## Notes

- NCBI E-utilities has a rate limit (3 req/s without a key). The scripts handle it with sleeps and, if the `NCBI_API_KEY` env var is set, automatically use it to raise the limit to 10 req/s.
- **Paywalled full text** is almost never needed — abstract + PMC OA full text covers the gene summaries. On the rare occasion a specific paper's paywalled full text is genuinely required, read [`docs/paywalled-access.md`](docs/paywalled-access.md) for the legal free-OA retrieval paths (PMC efetch / Unpaywall). Do not fabricate; mark "(abstract only)" if no OA copy exists.
