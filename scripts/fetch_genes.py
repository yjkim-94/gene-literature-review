#!/usr/bin/env python3
"""Resolve a keyword to a ranked gene list.

Free-text NCBI Gene esearch ranks by how well-studied a gene is overall, so
generic hubs (TP53, EGFR, APOE...) dominate and the genes actually specific to
the keyword get buried. Instead we use PubTator3: it NER-tags genes in the
keyword's papers, so ranking by mention frequency surfaces the genes truly
associated with the keyword (e.g. GPX4/FSP1/NRF2 for "ferroptosis"). NCBI Gene
esummary then filters to the requested organism and attaches clean symbols.

Genes are ranked by keyword-specificity computed on a PubTator ENTITY basis
(@GENE_<id> co-occurrence counts), not tiab string matching -- so a common-word
symbol like CAT is the catalase entity, never the word "cat". Ranking uses the
Wilson lower bound of that proportion so a high ratio from a handful of papers
can't outrank a real core gene backed by hundreds. The default sort also applies
a 0.5x demotion to immunoglobulin/TCR/HLA structural symbols, a strict
no-downside improvement validated in docs/cdrs-eval-findings.md; these recurrent
literature artifacts (e.g. IGHE for atopic dermatitis) are demoted, not dropped.
See DESIGN.md (설계 C/D).

The KEYWORD side can also be an entity: pass --entity @DISEASE_MESH:<id> (from
the query gate's MeSH resolution) and both discovery and the co-occurrence
numerator use the disease ENTITY, which unions the concept's surface synonyms
("atopic eczema", "infantile eczema") in one exact call -- grouping-less OR of
those synonyms collapses the PubTator parser (measured). Without --entity it
falls back to free-text --keyword (novel terms with no MeSH, e.g. cuproptosis).

Writes a tab-separated table (symbol, gene_id, name, co_papers, gene_papers,
specificity, spec_adj, below_floor, artifact, evidence_pmids) to --out -- opens
cleanly in Excel. evidence_pmids is ";"-joined. A sidecar <out>_all_scored.tsv holds
every scored candidate BEFORE the min_co/min_specificity filter, so the cutoff
can be set from the real spec_adj distribution instead of guessed.

--out defaults to output/<keyword-slug>/genes.tsv, a per-keyword run dir that
holds every artifact of the run (genes.tsv, genes_all_scored.tsv, lit/,
gene_literature_review.md). Separate keywords never overwrite each other, and
downstream steps locate their inputs/outputs by that dir -- no re-derived slug.
"""
import argparse
import collections
import concurrent.futures
import csv
import hashlib
import json
import math
import os
import random
import re
import statistics
import sys
import threading
import time
import urllib.parse
import urllib.request

import runlog
from runlog import info as log

PUBTATOR = "https://www.ncbi.nlm.nih.gov/research/pubtator3-api"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

ORGANISM_TAX = {"human": "Homo sapiens", "mouse": "Mus musculus", "rat": "Rattus norvegicus"}

# Score up to this many organism-matching candidates per requested gene. Scoring
# is the dominant cost (2 PubTator calls each), so we cap it at a multiple of
# --max rather than the whole scan: filters + organism drop candidates, so we
# must attempt more than --max to end up with --max. ponytail: 5x is a heuristic;
# raise if runs routinely return fewer than --max after filtering.
SCORE_MULTIPLE = 5
# ponytail: PubTator3 measured ceiling is 3 clean workers; 8+ mass 429. Raising
# this trips the rolling ~3-4 req/s sustained limit.
MAX_WORKERS = 3


def slug(keyword):
    """Keyword -> filesystem run-dir name: lowercase kebab-case, alnum only.

    Single source of truth for the run directory. Every downstream artifact
    (lit/, gene_literature_review.md) sits inside this dir, so the slug rule
    lives here only -- other steps derive their paths by directory locality.

    A non-ASCII / all-symbol keyword ("아토피", "!!!") strips to "" -- which would
    collapse the path to output/genes.tsv and silently overwrite every such run.
    Fall back to a short stable hash so distinct keywords still get distinct dirs.
    """
    s = re.sub(r"[^a-z0-9]+", "-", keyword.lower()).strip("-")
    return s or "kw-" + hashlib.md5(keyword.encode("utf-8")).hexdigest()[:8]


def _get(url):
    # 6 tries with growing backoff: a single transient blip on the first call
    # otherwise throws away hundreds of already-scored candidates.
    for attempt in range(6):
        try:
            with urllib.request.urlopen(url, timeout=90) as r:
                return r.read().decode()
        except Exception:
            time.sleep(1.5 * (attempt + 1))
    raise SystemExit(f"network failure: {url}")


def _key():
    k = os.environ.get("NCBI_API_KEY")
    return f"&api_key={k}" if k else ""


def search_text(keyword, entity):
    """PubTator search term for discovery/scan. When the keyword resolves to a
    concept ENTITY (e.g. @DISEASE_MESH:D003876), search that -- it unions all
    surface synonyms ("atopic eczema", "infantile eczema", ...) that free-text
    can't (grouping-less OR collapses the query; measured). Free-text keyword is
    the fallback for novel terms with no MeSH entity (cuproptosis, etc.)."""
    return f'"{entity}"' if entity else keyword


def gene_query(gid, entity):
    """The gene half of both the numerator and the denominator (total) query.
    Quoted (`"@GENE_<id>"`) on the entity path, bare otherwise -- so numerator and
    denominator use the SAME @GENE form and the co count can never exceed total."""
    return f'"@GENE_{gid}"' if entity else f"@GENE_{gid}"


def co_query(gid, keyword, entity):
    """Co-occurrence numerator query for a gene. The entity form
    `"@GENE_<id>" AND "@DISEASE_MESH:<id>"` (each token quoted -- unquoted the
    colon 400s) counts papers where the gene entity co-occurs with the disease
    ENTITY, so synonym papers are included in one exact call. Free-text is the
    fallback when no entity was resolved."""
    return f'{gene_query(gid, entity)} AND "{entity}"' if entity else f"@GENE_{gid} AND {keyword}"


def entity_candidates(keyword, top=6):
    """PubTator concept-entity candidates for a keyword -- objective resolution,
    not an AI guess. Each: {token, biotype, db_id, name}; `token` is PubTator's
    own entity id (e.g. @DISEASE_Dermatitis_Atopic), usable verbatim as --entity.
    Empty list means no entity (novel term like cuproptosis) -> free-text
    fallback. Lets the query gate pick the concept by evidence, not by dominant-
    sense bias (the subjective-canonical hazard this replaces)."""
    u = f"{PUBTATOR}/entity/autocomplete/?query={urllib.parse.quote(keyword)}"
    try:
        data = json.loads(_get(u))
    except ValueError:
        return []  # empty/malformed body -> treat as no candidates (free-text fallback)
    if not isinstance(data, list):
        return []
    return [{"token": c["_id"], "biotype": c.get("biotype", ""),
             "db_id": c.get("db_id", ""), "name": c.get("name", "")}
            for c in data[:top] if isinstance(c, dict) and c.get("_id")]


def rank_gene_ids(search_term, scan_papers):
    """Return GeneIDs ranked by mention frequency across the concept's papers."""
    runlog.section("SCAN")
    q = urllib.parse.quote(search_term)
    log(f"scan: collecting up to {scan_papers} PMIDs ...")

    def fetch_search_page(page):
        d = json.loads(_get(f"{PUBTATOR}/search/?text={q}&page={page}"))
        got = [str(r["pmid"]) for r in d.get("results", [])]
        return d, got

    pmids = []
    d, got = fetch_search_page(1)
    if got:
        pmids += got
    count = d.get("count", 0)
    pages_needed = max(1, (min(scan_papers, count) + 9) // 10)
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        for _, got in ex.map(fetch_search_page, range(2, pages_needed + 1)):
            if got:
                pmids += got
    pmids = pmids[:scan_papers]

    log(f"scan: collected {len(pmids)} PMIDs, tagging genes...")
    cnt = collections.Counter()
    docs_with_gene = 0

    def tag_chunk(i):
        chunk = ",".join(pmids[i:i + 10])
        bio = json.loads(_get(f"{PUBTATOR}/publications/export/biocjson?pmids={chunk}"))
        doc_gene_ids = []
        for doc in bio.get("PubTator3", []):
            seen = set()  # count each gene once per paper, not per mention
            for p in doc.get("passages", []):
                for a in p.get("annotations", []):
                    inf = a.get("infons", {})
                    gid = inf.get("identifier")
                    if inf.get("type") == "Gene" and gid:
                        seen.add(gid)
            doc_gene_ids.append(seen)
        return i, doc_gene_ids

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        for i, doc_gene_ids in ex.map(tag_chunk, range(0, len(pmids), 10)):
            if i % 100 == 0:  # progress every 100 papers (chunks are 10 each)
                log(f"scan: tagging {i}/{len(pmids)} papers "
                    f"· {len(cnt)} distinct genes so far")
            for seen in doc_gene_ids:
                if seen:
                    docs_with_gene += 1
                for gid in seen:
                    cnt[gid] += 1
    log(f"scan: {len(pmids)}/{scan_papers} papers fetched · {docs_with_gene} "
        f"with gene tags · {len(cnt)} distinct genes (candidate pool)")
    return cnt


def _pubtator_count(query):
    """Return (total match count, up to 3 top PMIDs) for a PubTator search."""
    d = json.loads(_get(f"{PUBTATOR}/search/?text={urllib.parse.quote(query)}"))
    return d.get("count", 0), [str(r.get("pmid")) for r in d.get("results", [])[:3]]


def wilson_lower(k, n, z=1.96):
    """Lower bound of the Wilson score interval for proportion k/n.

    Ranking on the point estimate k/n lets a 3/3 gene (specificity 1.0 on 3
    papers) outrank a real core gene at 140/400; the lower bound collapses
    tiny-n to ~0.3-0.4 while leaving large-n near its point estimate, so
    understudied genes are demoted rather than promoted. See DESIGN.md (설계 D).
    """
    if n == 0:
        return 0.0
    # k should never exceed n (co-occurrence is a subset of the gene's papers),
    # but two independent PubTator count calls can transiently disagree. Clamp so
    # p>1 can't drive the sqrt below zero -> a complex result -> round() crash.
    p = min(k, n) / n
    z2 = z * z
    center = p + z2 / (2 * n)
    margin = z * ((p * (1 - p) / n + z2 / (4 * n * n)) ** 0.5)
    return (center - margin) / (1 + z2 / n)


# ---- CDRS: cross-disease relative specificity (method_dev.md §6) ------------
# OBSERVE ONLY (§6.7 step 2): computes z_rel / breadth_random / hub_penalty and
# adds them as columns, but ranking stays on spec_adj. Enabled by --rank cdrs.
# These columns exist to be eyeballed on real runs before they drive rank_score.
CDRS_ALPHA = 0.5
CDRS_EPS = 1e-9
# ponytail: PLACEHOLDER floor (method_dev §7-①) -- same "arbitrary constant"
# critique as the old 0.05; breadth's specificity bar, to be derived/tuned later.
CDRS_BAR_B = 0.02
CDRS_COLS = ["z_rel", "breadth_random", "hub_penalty"]


def load_panel(path):
    """panel_random.tsv -> list of (token, disease_total). Skips # comments and
    the header. disease_total is needed to pick volume-matched pseudo-diseases
    (§6.2); tokens alone drive the z_rel/breadth panel."""
    panel = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("#") or line.startswith("token\t"):
                continue
            p = line.rstrip("\n").split("\t")
            if len(p) >= 2 and p[0].strip() and p[1].strip().isdigit():
                panel.append((p[0].strip(), int(p[1].strip())))
    return panel


def load_cache(cache_dir):
    """(gene_id, token) -> count, persisted across runs. Panel co-counts are
    keyword-INDEPENDENT, so reusing them across keywords is the whole point of
    the cache (method_dev §6.4) -- without it every run re-issues thousands of
    identical PubTator calls. Returns (dict, path)."""
    path = os.path.join(cache_dir, "pubtator_counts.tsv")
    cache = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                p = line.rstrip("\n").split("\t")
                if len(p) == 3 and p[2].lstrip("-").isdigit():  # tolerate stray/header lines
                    cache[(p[0], p[1])] = int(p[2])
    return cache, path


def save_cache(cache, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        for (gid, tok), n in sorted(cache.items()):
            f.write(f"{gid}\t{tok}\t{n}\n")


def panel_count(gid, token, cache, cache_lock=None):
    """Cache-backed co-occurrence count of gene gid with a panel disease token.

    ponytail: only these panel co-counts are cached -- they are the O(genes x
    panel) cost that reruns must not repay. The gene total / query co-count are
    fetched once each in the spec scoring path (and query-co carries evidence
    PMIDs that don't belong in a count cache), so they are not routed here yet;
    complete the §6.4 full wrapper when rank_score wiring lands.
    """
    key = (gid, token)
    if key not in cache:
        n, _ = _pubtator_count(co_query(gid, "", token))
        if cache_lock:
            with cache_lock:
                cache[key] = n
        else:
            cache[key] = n
    return cache[key]


def _logit(s):
    return math.log(s / (1 - s))


def cdrs_enrich(rows, panel_tokens, cache, cache_path=None):
    """Add z_rel / breadth_random / hub_penalty to each scored row (OBSERVE only).

    For each gene, compare its query-disease specificity to its specificity
    across the random disease panel:
      s(g,d)  = (co + a) / (gene_papers + 2a)    ; x = logit(s)
      z_rel   = (x_query - median_panel x) / (1.4826*MAD + eps)   -- robust z
      breadth = fraction of panel where Wilson-lower(co_panel) >= BAR_B
    A gene no more specific to the query than to random diseases scores z_rel~0;
    a pleiotropic hub is broad (high breadth -> hub_penalty demotes it). Ranking
    is NOT touched here. Mutates the row dicts in place.
    """
    a, eps = CDRS_ALPHA, CDRS_EPS
    n_done = [0]
    cache_lock = threading.Lock()

    def flush_cache():
        if cache_path:
            with cache_lock:
                save_cache(cache, cache_path)

    def enrich(row):
        gid, co, total = row["gene_id"], row["co_papers"], row["gene_papers"]
        # panel counts are sequential inside one gene so we don't exceed the
        # ~3-worker PubTator ceiling (genes run in parallel, see below). Cache
        # writes are locked so incremental flushes never iterate a mutating dict.
        cs = [panel_count(gid, tok, cache, cache_lock) for tok in panel_tokens]
        # clamp co/c to total before logit: two independent PubTator count calls
        # can transiently disagree (co > total), which would push s>1 and crash
        # math.log -- same guard wilson_lower already applies.
        x_d = _logit((min(co, total) + a) / (total + 2 * a))
        xs = [_logit((min(c, total) + a) / (total + 2 * a)) for c in cs]
        med = statistics.median(xs)
        mad = statistics.median([abs(x - med) for x in xs])  # 0 if panel uniform -> eps guards
        breadth = sum(wilson_lower(c, total) >= CDRS_BAR_B for c in cs) / len(cs)
        row["z_rel"] = round((x_d - med) / (1.4826 * mad + eps), 4)
        row["breadth_random"] = round(breadth, 4)
        row["hub_penalty"] = round(1 - min(breadth, 0.8), 4)
        n_done[0] += 1
        log(f"cdrs [{n_done[0]}/{len(rows)}]: {row['symbol']} "
            f"z_rel={row['z_rel']} breadth={row['breadth_random']}")
        flush_cache()

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        list(ex.map(enrich, rows))


# ---- Stage 3: permutation-null threshold + track assignment (§6.7 step 3) ----
# Still OBSERVE: T_emp/pass_stage1 populate the `track` column but do NOT reorder
# the list. T_emp's exact null is a KNOWN open question (method_dev §7-③); this
# is the doc's provisional pooled-Q0.95 definition, safe to eyeball because it
# only labels tracks here.
STAGE3_COLS = ["pass_stage1", "track"]
# ARTIFACT_CLASSES as a symbol-regex class test, NOT a hardcoded gene blocklist
# (§6.3). esummary gene-type == pseudo is deferred to step 4 (needs the record
# carried into rows); the immunoglobulin/TCR/HLA symbols cover the AD case (IGHE).
# The Ig arms require an isotype/segment letter followed only by digits/hyphens
# (or end) so real coding genes that merely start with IGH -- IGHMBP2, IGHMBP-
# like helicases -- are NOT swept in. TR[ABGD][VJDC] and HLA- are already tight.
ARTIFACT_RE = re.compile(r"^(IG[HKL][ACDEGJMV][\d-]*$|IG[HKL]$|TR[ABGD][VJDC]|HLA-)")
T_EMP_FALLBACK = 0.05  # §6.8: too few volume-matched pseudo-diseases -> old cut


def is_artifact(symbol):
    return bool(ARTIFACT_RE.match(symbol or ""))


def _percentile(sorted_vals, q):
    """Nearest-rank q-quantile of an already-sorted list (no numpy dep).

    index = ceil(q*n)-1, the standard nearest-rank rule -- round(q*(n-1)) drifts
    by one for some n via banker's rounding (n=31, q=.95 -> 28 not 29)."""
    if not sorted_vals:
        return 0.0
    i = min(max(math.ceil(q * len(sorted_vals)) - 1, 0), len(sorted_vals) - 1)
    return sorted_vals[i]


def select_pseudo(panel, m_d, n_p, seed):
    """Pick up to n_p volume-matched pseudo-disease tokens (seed-fixed).

    Volume matching is the point (§6.2): a chance-level threshold is only fair
    against diseases of similar paper volume. Start at [0.5*M_D, 2*M_D] and
    widen x2, x3 only if the window holds fewer than n_p. Returns (tokens,
    too_few) -- too_few triggers the T_emp fallback (§6.8)."""
    window = []
    for k in (1, 2, 3):
        lo, hi = m_d / (2 * k), 2 * k * m_d
        window = [t for t, d in panel if lo <= d <= hi]
        if len(window) >= n_p:
            break
    rng = random.Random(seed)
    rng.shuffle(window)
    pseudo = window[:n_p]
    # fallback keys off the actually-sampled count: --pseudo-n 5 is too small for
    # a stable null even if the window held more (§6.8 "<10 -> fallback").
    return pseudo, len(pseudo) < 10


def compute_t_emp(rows, pseudo_tokens, cache):
    """T_emp = Q0.95 of Wilson-lower(co, G_g) pooled over every candidate gene x
    pseudo-disease (§6.3). All counts are cache hits (pseudo-diseases are a subset
    of the already-enriched panel), so this adds ~no network cost."""
    pool = []
    for r in rows:
        gid, total = r["gene_id"], r["gene_papers"]
        for tok in pseudo_tokens:
            pool.append(wilson_lower(panel_count(gid, tok, cache), total))
    pool.sort()
    return _percentile(pool, 0.95)


def assign_tracks(rows, t_emp, min_co, min_gene_papers):
    """pass_stage1 + 4-track label per gene (§6.5 priority order). OBSERVE only."""
    med_g = statistics.median([r["gene_papers"] for r in rows]) if rows else 0
    for r in rows:
        r["pass_stage1"] = (r["co_papers"] >= min_co and r["gene_papers"] >= min_gene_papers
                            and wilson_lower(r["co_papers"], r["gene_papers"]) >= t_emp)
        if is_artifact(r["symbol"]):
            r["track"] = "artifact"
        elif not r["pass_stage1"] and r["gene_papers"] < med_g:
            r["track"] = "exploratory"
        elif r["breadth_random"] >= 0.5:
            r["track"] = "related_pleiotropic"
        elif r["pass_stage1"]:
            r["track"] = "established"
        else:
            r["track"] = "exploratory"


def rank_and_floor(rows, min_gene_papers):
    """Order rows by specificity lower bound, demoting known artifact symbols.

    The Wilson lower bound alone is not enough: 3/3 scores ~0.44, still above a
    real 140/400 core gene (~0.31). So genes with fewer than min_gene_papers
    total papers are demoted below all floor-passing genes (not deleted -- they
    stay in the large list). This is a LOW ABSOLUTE floor, not a percentile of
    the candidate distribution: a relative floor wrongly demoted FDX1 (1565
    papers, the best cuproptosis core gene) just because sibling core genes had
    2000-3700 papers. A low absolute floor sinks true artifacts (n<10) while
    keeping niche core genes (cuproptosis ~10-25 papers). See DESIGN.md (설계 D/E).
    """
    for r in rows:
        r["below_floor"] = r["gene_papers"] < min_gene_papers
    rows.sort(
        key=lambda r: (
            not r["below_floor"],
            (0.5 if is_artifact(r["symbol"]) else 1.0) * r["spec_adj"],
        ),
        reverse=True,
    )
    return rows


def pick_candidates(cnt, want, pool):
    """Walk candidates in co-mention order, keep organism-matching ones up to pool.

    esummary (symbol + organism) is cheap and batched (1 call / 100 ids), so we
    filter to the requested organism HERE -- before the expensive per-candidate
    PubTator scoring -- and never waste 2 calls on a non-organism gene. Returns
    (gid, esummary record) pairs in co-mention order, at most `pool` of them.
    """
    cands = [g for g, _ in cnt.most_common()]
    picked = []
    for i in range(0, len(cands), 100):
        batch = cands[i:i + 100]
        ids = ",".join(batch)
        su = json.loads(_get(f"{EUTILS}/esummary.fcgi?db=gene&id={ids}&retmode=json{_key()}"))["result"]
        for gid in batch:
            rec = su.get(gid)
            if not rec or rec.get("organism", {}).get("scientificname") != want:
                continue
            if not rec.get("name"):
                continue
            picked.append((gid, rec))
            if len(picked) >= pool:
                return picked
        time.sleep(0.34)
    return picked


def resolve_human(cnt, keyword, entity, organism, max_genes, min_spec, min_co, min_gene_papers):
    """Rank candidate genes by keyword-specificity on a PubTator entity basis.

    Specificity is (papers where the gene ENTITY co-occurs with the keyword) /
    (papers where the gene entity appears), both from PubTator @GENE_<id> search
    counts -- NOT tiab strings. Entity matching means a common-word symbol (CAT,
    REST, SET) resolves to its gene, not the English word, so it can't be
    inflated by unrelated text. Genes are ranked by the Wilson lower bound of
    that proportion with a keyword-relative paper-count floor (min_spec applies
    to the lower bound, min_co guards degenerate tiny counts). See DESIGN.md
    (설계 C/D/E).

    Only the top SCORE_MULTIPLE * max_genes organism-matching candidates (by
    co-mention) are scored -- the co-mention prefilter both bounds the dominant
    cost and drops the long tail of one-off NER mistags before scoring.
    """
    runlog.section("FILTER")
    want = ORGANISM_TAX.get(organism.lower(), organism)
    pool = SCORE_MULTIPLE * max_genes
    picked = pick_candidates(cnt, want, pool)
    log(f"organism filter: {len(cnt)} candidates -> {len(picked)} {organism} "
        f"matches to score (cap {pool})")

    runlog.section("SCORE")
    rows = []
    all_scored = []  # every scored candidate, pre-filter, for the cutoff sidecar
    n_zero = 0  # scored candidates with no papers at all (dropped before filter)

    def score_candidate(item):
        i, (gid, rec) = item
        sym = rec.get("name", "")
        total, _ = _pubtator_count(gene_query(gid, entity))
        if total == 0:
            return i, sym, None, None
        co, evidence_pmids = _pubtator_count(co_query(gid, keyword, entity))
        spec = co / total
        lower = wilson_lower(co, total)
        row = {"symbol": sym, "gene_id": gid, "name": rec.get("description", ""),
               "co_papers": co, "gene_papers": total,
               "specificity": round(spec, 4), "spec_adj": round(lower, 4),
               "evidence_pmids": evidence_pmids}
        return i, sym, row, lower

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        for i, sym, row, lower in ex.map(score_candidate, enumerate(picked)):
            log(f"specificity [{i + 1}/{len(picked)}]: {sym}")
            if row is None:
                n_zero += 1
                continue
            co = row["co_papers"]
            all_scored.append(row)
            if co < min_co or lower < min_spec:
                continue
            rows.append(row)
    log(f"scored {len(all_scored)} · dropped {n_zero} (no papers) · "
        f"passed filter {len(rows)} (min_co={min_co}, min_spec={min_spec})")
    return rank_and_floor(rows, min_gene_papers)[:max_genes], rank_and_floor(all_scored, min_gene_papers)


TSV_COLS = ["symbol", "gene_id", "name", "co_papers", "gene_papers",
            "specificity", "spec_adj", "below_floor", "artifact", "evidence_pmids"]


def write_tsv(path, genes):
    # CDRS columns appear only when --rank cdrs populated them (observe mode);
    # the default spec path now adds only the explicit artifact marker.
    extra = [c for c in CDRS_COLS + STAGE3_COLS if genes and c in genes[0]]
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(TSV_COLS + extra)
        for g in genes:
            row = [g["symbol"], g["gene_id"], g["name"], g["co_papers"],
                   g["gene_papers"], g["specificity"], g["spec_adj"],
                   str(g["below_floor"]).lower(),
                   str(is_artifact(g["symbol"])).lower(),
                   ";".join(g["evidence_pmids"])]
            row += [g[c] for c in extra]
            w.writerow(row)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keyword", required=True,
                    help="human-readable concept term; used for the run-dir slug and as "
                         "free-text fallback when --entity is absent")
    ap.add_argument("--entity", default="",
                    help="PubTator concept entity token, e.g. @DISEASE_MESH:D003876 "
                         "(from the MeSH resolution in the query gate). Unions all surface "
                         "synonyms. Omit for novel terms with no MeSH entity.")
    ap.add_argument("--organism", default="human")
    ap.add_argument("--max", type=int, default=20,
                    help="target gene count; also caps scoring at 5x this (SCORE_MULTIPLE)")
    ap.add_argument("--scan", type=int, default=60,
                    help="how many keyword papers to scan for candidate genes")
    ap.add_argument("--min-specificity", type=float, default=0.05,
                    help="drop genes whose specificity LOWER BOUND is below this")
    ap.add_argument("--min-co", type=int, default=5,
                    help="require at least this many keyword+gene co-occurrence papers")
    ap.add_argument("--min-gene-papers", type=int, default=10,
                    help="demote genes with fewer than this many total papers (artifact floor)")
    ap.add_argument("--rank", choices=["spec", "cdrs"], default="spec",
                    help="spec (default, current behavior) or cdrs: also compute the "
                         "cross-disease z_rel/breadth/hub_penalty columns (OBSERVE only -- "
                         "ranking still on spec_adj). method_dev.md §6")
    ap.add_argument("--panel-random", default=os.path.join("scripts", "data", "panel_random.tsv"),
                    help="B_random disease panel for --rank cdrs")
    ap.add_argument("--cache-dir", default=os.path.join("output", ".cache"),
                    help="PubTator count cache dir (shared across keywords; panel counts "
                         "are keyword-independent)")
    ap.add_argument("--pseudo-n", type=int, default=30,
                    help="number of volume-matched pseudo-diseases for the T_emp null (--rank cdrs)")
    ap.add_argument("--seed", type=int, default=42,
                    help="RNG seed for pseudo-disease sampling (reproducible T_emp)")
    ap.add_argument("--out", help="output TSV path; default output/<keyword-slug>/genes.tsv")
    ap.add_argument("--resolve", action="store_true",
                    help="resolve --keyword to PubTator concept-entity candidates "
                         "(token, biotype, paper count) and exit -- pick one and pass it as --entity")
    args = ap.parse_args()

    # --resolve: objective entity lookup for the query gate, then stop. Prints
    # candidates with their PubTator paper count so the concept is chosen by
    # evidence volume, not by the AI's dominant-sense guess.
    if args.resolve:
        cands = entity_candidates(args.keyword)
        if not cands:
            print(f"no PubTator entity for '{args.keyword}' -- novel term; "
                  f"run without --entity (free-text fallback)", file=sys.stderr)
        print("token\tbiotype\tcount\tname")
        for c in cands:
            n, _ = _pubtator_count(f'"{c["token"]}"')
            time.sleep(0.34)
            print(f"{c['token']}\t{c['biotype']}\t{n}\t{c['name']}")
        return

    # Run-dir is derived from the keyword so separate keywords never collide and
    # every artifact of one run lives together. --out still overrides if given.
    out = args.out or os.path.join("output", slug(args.keyword), "genes.tsv")

    # Create the run dir and open the log BEFORE any work, so output/<slug>/
    # appears immediately and the phase log fills line-by-line (info() flushes)
    # -- the run can be watched live via `tail -f`.
    runlog.open_log(os.path.dirname(out) or ".", "phase1_fetch_genes.log")
    if not os.environ.get("NCBI_API_KEY"):
        log("no NCBI_API_KEY set -- running at 3 req/s. Set the env var for 10 req/s "
            "(see README > Notes).")

    cnt = rank_gene_ids(search_text(args.keyword, args.entity), args.scan)
    if not cnt:
        log("no genes found for keyword")
    genes, all_scored = resolve_human(cnt, args.keyword, args.entity, args.organism, args.max,
                                      args.min_specificity, args.min_co,
                                      args.min_gene_papers)

    # --rank cdrs: enrich every scored candidate with the cross-disease columns
    # (all_scored dicts are shared with genes, so both outputs pick them up). This
    # is observe-only -- rank_and_floor already ordered by spec_adj and we don't
    # re-sort. §6.7 steps 1-2.
    if args.rank == "cdrs":
        if not os.path.exists(args.panel_random):
            sys.exit(f"--rank cdrs needs a panel file but {args.panel_random} is missing "
                     f"(build it: python scripts/data/build_panel_random.py)")
        runlog.section("CDRS")
        panel = load_panel(args.panel_random)
        if not panel:
            sys.exit(f"panel {args.panel_random} has no disease tokens (all comment/blank)")
        tokens = [t for t, _ in panel]
        cache, cache_path = load_cache(args.cache_dir)
        log(f"cdrs: {len(all_scored)} genes x {len(panel)} panel diseases "
            f"(cache: {len(cache)} entries loaded)")
        try:
            cdrs_enrich(all_scored, tokens, cache, cache_path)
        finally:
            save_cache(cache, cache_path)

        # Stage 3: volume-matched pseudo-diseases -> T_emp -> pass_stage1 + track.
        # pseudo counts are a subset of the panel just enriched, so this is ~free.
        m_d = _pubtator_count(search_text(args.keyword, args.entity))[0]
        pseudo, too_few = select_pseudo(panel, m_d, args.pseudo_n, args.seed)
        if too_few:
            t_emp = T_EMP_FALLBACK
            log(f"cdrs: only {len(pseudo)} volume-matched pseudo-diseases (<10) -> "
                f"T_emp fallback {t_emp} (method_dev §6.8)")
        else:
            t_emp = compute_t_emp(all_scored, pseudo, cache)
            log(f"cdrs: M_D={m_d}, {len(pseudo)} pseudo-diseases -> T_emp={t_emp:.4f}")
        assign_tracks(all_scored, t_emp, args.min_co, args.min_gene_papers)
        save_cache(cache, cache_path)
        log(f"cdrs: cache now {len(cache)} entries -> {cache_path}")
        for tr, n in sorted(collections.Counter(g["track"] for g in all_scored).items()):
            log(f"cdrs track: {tr} = {n}")

    write_tsv(out, genes)
    # sidecar dump of every scored candidate (pre-filter) so the spec_adj
    # distribution is visible and the cutoff can be set from data, not guessed.
    root, ext = os.path.splitext(out)
    all_path = f"{root}_all_scored{ext or '.tsv'}"
    write_tsv(all_path, all_scored)
    runlog.section("RESULT")
    log(f"{len(genes)} genes -> {out}")
    log(f"{len(all_scored)} scored (pre-filter) -> {all_path}")
    for g in genes:
        log(f"  {g['symbol']} (spec={g['specificity']}, adj={g['spec_adj']}, "
            f"co={g['co_papers']}/{g['gene_papers']}): {g['name']}")


if __name__ == "__main__":
    main()
