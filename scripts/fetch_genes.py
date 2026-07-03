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
can't outrank a real core gene backed by hundreds. See DESIGN.md (설계 C/D).

Writes a tab-separated table (symbol, gene_id, name, co_papers, gene_papers,
specificity, spec_lower, below_floor, evidence_pmids) to --out -- opens cleanly
in Excel. evidence_pmids is ";"-joined.
"""
import argparse
import collections
import csv
import json
import os
import sys
import time
import urllib.parse
import urllib.request

PUBTATOR = "https://www.ncbi.nlm.nih.gov/research/pubtator3-api"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

ORGANISM_TAX = {"human": "Homo sapiens", "mouse": "Mus musculus", "rat": "Rattus norvegicus"}


def _get(url):
    for _ in range(3):
        try:
            with urllib.request.urlopen(url, timeout=90) as r:
                return r.read().decode()
        except Exception:
            time.sleep(1.5)
    raise SystemExit(f"network failure: {url}")


def _key():
    k = os.environ.get("NCBI_API_KEY")
    return f"&api_key={k}" if k else ""


def rank_gene_ids(keyword, scan_papers):
    """Return GeneIDs ranked by mention frequency across the keyword's papers."""
    q = urllib.parse.quote(keyword)
    pmids = []
    page = 1
    while len(pmids) < scan_papers:
        d = json.loads(_get(f"{PUBTATOR}/search/?text={q}&page={page}"))
        got = [str(r["pmid"]) for r in d.get("results", [])]
        if not got:
            break
        pmids += got
        page += 1
        time.sleep(0.3)
    pmids = pmids[:scan_papers]

    cnt = collections.Counter()
    for i in range(0, len(pmids), 10):
        chunk = ",".join(pmids[i:i + 10])
        bio = json.loads(_get(f"{PUBTATOR}/publications/export/biocjson?pmids={chunk}"))
        for doc in bio.get("PubTator3", []):
            seen = set()  # count each gene once per paper, not per mention
            for p in doc.get("passages", []):
                for a in p.get("annotations", []):
                    inf = a.get("infons", {})
                    gid = inf.get("identifier")
                    if inf.get("type") == "Gene" and gid:
                        seen.add(gid)
            for gid in seen:
                cnt[gid] += 1
        time.sleep(0.4)
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
    p = k / n
    z2 = z * z
    center = p + z2 / (2 * n)
    margin = z * ((p * (1 - p) / n + z2 / (4 * n * n)) ** 0.5)
    return (center - margin) / (1 + z2 / n)


def rank_and_floor(rows, min_gene_papers):
    """Order rows by specificity lower bound, demoting tiny-denominator genes.

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
    rows.sort(key=lambda r: (not r["below_floor"], r["spec_lower"]), reverse=True)
    return rows


def resolve_human(cnt, keyword, organism, max_genes, cand_pool, min_spec, min_co, min_gene_papers):
    """Rank candidate genes by keyword-specificity on a PubTator entity basis.

    Specificity is (papers where the gene ENTITY co-occurs with the keyword) /
    (papers where the gene entity appears), both from PubTator @GENE_<id> search
    counts -- NOT tiab strings. Entity matching means a common-word symbol (CAT,
    REST, SET) resolves to its gene, not the English word, so it can't be
    inflated by unrelated text. Genes are ranked by the Wilson lower bound of
    that proportion with a keyword-relative paper-count floor (min_spec applies
    to the lower bound, min_co guards degenerate tiny counts). See DESIGN.md
    (설계 C/D/E).
    """
    want = ORGANISM_TAX.get(organism.lower(), organism)
    # top candidates by PubTator co-mention -> resolve to human symbols
    cands = [g for g, _ in cnt.most_common(cand_pool)]
    scored = {}
    for i in range(0, len(cands), 100):
        ids = ",".join(cands[i:i + 100])
        su = json.loads(_get(f"{EUTILS}/esummary.fcgi?db=gene&id={ids}&retmode=json{_key()}"))["result"]
        for gid in su.get("uids", []):
            scored[gid] = su[gid]
        time.sleep(0.34)

    rows = []
    for i, gid in enumerate(cands):
        rec = scored.get(gid)
        if not rec or rec.get("organism", {}).get("scientificname") != want:
            continue
        sym = rec.get("name", "")
        if not sym:
            continue
        print(f"specificity [{i + 1}/{len(cands)}]: {sym}", file=sys.stderr)
        total, _ = _pubtator_count(f"@GENE_{gid}")
        time.sleep(0.34)
        if total == 0:
            continue
        co, evidence_pmids = _pubtator_count(f"@GENE_{gid} AND {keyword}")
        time.sleep(0.34)
        spec = co / total
        lower = wilson_lower(co, total)
        if co < min_co or lower < min_spec:
            continue
        rows.append({"symbol": sym, "gene_id": gid, "name": rec.get("description", ""),
                     "co_papers": co, "gene_papers": total,
                     "specificity": round(spec, 4), "spec_lower": round(lower, 4),
                     "evidence_pmids": evidence_pmids})
    return rank_and_floor(rows, min_gene_papers)[:max_genes]


TSV_COLS = ["symbol", "gene_id", "name", "co_papers", "gene_papers",
            "specificity", "spec_lower", "below_floor", "evidence_pmids"]


def write_tsv(path, genes):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(TSV_COLS)
        for g in genes:
            w.writerow([g["symbol"], g["gene_id"], g["name"], g["co_papers"],
                        g["gene_papers"], g["specificity"], g["spec_lower"],
                        str(g["below_floor"]).lower(), ";".join(g["evidence_pmids"])])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keyword", required=True)
    ap.add_argument("--organism", default="human")
    ap.add_argument("--max", type=int, default=20)
    ap.add_argument("--scan", type=int, default=60,
                    help="how many keyword papers to scan for candidate genes")
    ap.add_argument("--cand-pool", type=int, default=40,
                    help="how many top candidates to score for specificity")
    ap.add_argument("--min-specificity", type=float, default=0.05,
                    help="drop genes whose specificity LOWER BOUND is below this")
    ap.add_argument("--min-co", type=int, default=5,
                    help="require at least this many keyword+gene co-occurrence papers")
    ap.add_argument("--min-gene-papers", type=int, default=10,
                    help="demote genes with fewer than this many total papers (artifact floor)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    cnt = rank_gene_ids(args.keyword, args.scan)
    if not cnt:
        print("no genes found for keyword", file=sys.stderr)
    genes = resolve_human(cnt, args.keyword, args.organism, args.max,
                          args.cand_pool, args.min_specificity, args.min_co,
                          args.min_gene_papers)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    write_tsv(args.out, genes)
    print(f"{len(genes)} genes -> {args.out}", file=sys.stderr)
    for g in genes:
        print(f"  {g['symbol']} (spec={g['specificity']}, lower={g['spec_lower']}, "
              f"co={g['co_papers']}/{g['gene_papers']}): {g['name']}", file=sys.stderr)


if __name__ == "__main__":
    main()
