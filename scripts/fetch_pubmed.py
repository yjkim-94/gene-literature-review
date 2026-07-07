#!/usr/bin/env python3
"""Fetch PubMed abstracts per gene into per-gene JSON files.

For each gene: esearch (gene + keyword) -> top N PMIDs -> efetch abstracts.
Marks access level as full-text when a PMC open-access id exists, else
abstract-only. Abstracts are written to files, never returned to the caller's
context -- that is the whole point (keeps token cost linear in gene count).
"""
import argparse
import csv
import json
import os
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import runlog
from runlog import info as log

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def _get(url):
    # 6 tries with growing backoff: a transient blip shouldn't lose a gene's
    # whole abstract fetch (matches fetch_genes.py's retry policy).
    for attempt in range(6):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.read().decode()
        except Exception:
            time.sleep(1.5 * (attempt + 1))
    raise SystemExit(f"network failure: {url}")


def _key():
    k = os.environ.get("NCBI_API_KEY")
    return f"&api_key={k}" if k else ""


def _sleep():
    # 3 req/s without a key, 10 with. Stay under the limit.
    time.sleep(0.11 if os.environ.get("NCBI_API_KEY") else 0.34)


def search_pmids(gene, keyword, n):
    # no keyword -> general gene literature (user-provided gene list case)
    term = urllib.parse.quote(f"{gene} AND {keyword}" if keyword else gene)
    url = f"{EUTILS}/esearch.fcgi?db=pubmed&term={term}&retmax={n}&sort=relevance&retmode=json{_key()}"
    return json.loads(_get(url))["esearchresult"].get("idlist", [])


def parse_pubmed_xml(xml_text):
    """Parse an efetch abstract XML into paper records. Split out from the network
    call so the itertext() extraction (the part that silently broke on inline
    markup) is testable offline."""
    root = ET.fromstring(xml_text)
    recs = []
    for art in root.findall(".//PubmedArticle"):
        pmid = art.findtext(".//PMID", "")
        # itertext(), not .text/findtext: AbstractText and ArticleTitle wrap inline
        # markup (<i>, <sub>, structured-abstract labels), so .text is None/partial
        # and drops the body when it starts with a child element (measured: PMID
        # 34106037's abstract came back empty under .text).
        title_el = art.find(".//ArticleTitle")
        title = "".join(title_el.itertext()).strip() if title_el is not None else ""
        abstract = " ".join("".join(t.itertext()) for t in art.findall(".//Abstract/AbstractText")).strip()
        year = art.findtext(".//PubDate/Year", "") or art.findtext(".//PubDate/MedlineDate", "")
        journal = art.findtext(".//Journal/Title", "") or ""
        pmcid = None
        for aid in art.findall(".//ArticleId"):
            if aid.get("IdType") == "pmc":
                pmcid = aid.text
        recs.append({
            "pmid": pmid, "title": title, "abstract": abstract,
            "year": year, "journal": journal,
            "access": "full-text" if pmcid else "abstract-only",
            "pmcid": pmcid,
        })
    return recs


def fetch_abstracts(pmids):
    if not pmids:
        return []
    ids = ",".join(pmids)
    url = f"{EUTILS}/efetch.fcgi?db=pubmed&id={ids}&rettype=abstract&retmode=xml{_key()}"
    return parse_pubmed_xml(_get(url))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--genes", required=True, help="genes.tsv from fetch_genes.py")
    ap.add_argument("--keyword", default="", help="omit for general gene literature (user-provided list)")
    ap.add_argument("--per-gene", type=int, default=5)
    ap.add_argument("--out-dir", help="default: lit/ next to --genes (same run dir)")
    args = ap.parse_args()

    # Default the output beside genes.tsv so the run dir stays self-contained
    # and the slug (owned by fetch_genes.py) is never re-derived here.
    out_dir = args.out_dir or os.path.join(os.path.dirname(args.genes) or ".", "lit")

    # Log into the run dir (parent of lit/) so scan + literature share a folder.
    runlog.open_log(os.path.dirname(out_dir) or ".", "phase2_fetch_pubmed.log")
    if not os.environ.get("NCBI_API_KEY"):
        log("no NCBI_API_KEY set -- running at 3 req/s. Set the env var for 10 req/s "
            "(see README > Notes).")

    with open(args.genes, encoding="utf-8", newline="") as f:
        genes = list(csv.DictReader(f, delimiter="\t"))
    os.makedirs(out_dir, exist_ok=True)

    runlog.section("COLLECT")
    log(f"{len(genes)} genes · top {args.per_gene} papers each -> {out_dir}")
    for i, g in enumerate(genes):
        sym = g["symbol"]
        pmids = search_pmids(sym, args.keyword, args.per_gene)
        _sleep()
        recs = fetch_abstracts(pmids)
        _sleep()
        out = os.path.join(out_dir, f"{sym}.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"symbol": sym, "name": g.get("name", ""), "papers": recs},
                      f, ensure_ascii=False, indent=2)
        n_ft = sum(1 for r in recs if r["access"] == "full-text")
        log(f"[{i + 1}/{len(genes)}] {sym}: {len(recs)} papers ({n_ft} full-text) -> {out}")

    runlog.section("RESULT")
    log(f"done: {len(genes)} genes -> {out_dir}")


if __name__ == "__main__":
    main()
