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
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def _get(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read().decode()


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


def fetch_abstracts(pmids):
    if not pmids:
        return []
    ids = ",".join(pmids)
    url = f"{EUTILS}/efetch.fcgi?db=pubmed&id={ids}&rettype=abstract&retmode=xml{_key()}"
    root = ET.fromstring(_get(url))
    recs = []
    for art in root.findall(".//PubmedArticle"):
        pmid = art.findtext(".//PMID", "")
        title = art.findtext(".//ArticleTitle", "") or ""
        abstract = " ".join(t.text or "" for t in art.findall(".//Abstract/AbstractText")).strip()
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--genes", required=True, help="genes.tsv from fetch_genes.py")
    ap.add_argument("--keyword", default="", help="omit for general gene literature (user-provided list)")
    ap.add_argument("--per-gene", type=int, default=5)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    with open(args.genes, encoding="utf-8", newline="") as f:
        genes = list(csv.DictReader(f, delimiter="\t"))
    os.makedirs(args.out_dir, exist_ok=True)

    for g in genes:
        sym = g["symbol"]
        pmids = search_pmids(sym, args.keyword, args.per_gene)
        _sleep()
        recs = fetch_abstracts(pmids)
        _sleep()
        out = os.path.join(args.out_dir, f"{sym}.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"symbol": sym, "name": g.get("name", ""), "papers": recs},
                      f, ensure_ascii=False, indent=2)
        n_ft = sum(1 for r in recs if r["access"] == "full-text")
        print(f"{sym}: {len(recs)} papers ({n_ft} full-text) -> {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
