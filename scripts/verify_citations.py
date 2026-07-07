#!/usr/bin/env python3
"""Verify review citations against per-gene literature JSON files.

The summarizer is instructed to cite only PMIDs from lit/<SYMBOL>.json. This
script checks that mechanically, with no network or AI judgment, so invented or
misplaced citations fail the pipeline.
"""
import argparse
import glob
import json
import os
import re
import sys

PMID_RE = re.compile(r"PMID:\s*(\d+)")
URL_RE = re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)")
HEADER_RE = re.compile(r"^###\s+(\S+)")


def extract_citations(md_text):
    """Return PMIDs grouped by the current gene section."""
    citations = {}
    symbol = None
    for line in md_text.splitlines():
        m = HEADER_RE.match(line)
        if m:
            symbol = m.group(1)
        pmids = set(PMID_RE.findall(line)) | set(URL_RE.findall(line))
        if pmids:
            citations.setdefault(symbol, set()).update(pmids)
    return citations


def lit_pmids(lit_dir, symbol):
    """Set of pmid strings in <lit_dir>/<symbol>.json, or None if missing."""
    path = os.path.join(lit_dir, f"{symbol}.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {str(p.get("pmid", "")) for p in data.get("papers", []) if p.get("pmid")}


def _all_lit_pmids(lit_dir):
    pmids = set()
    for path in glob.glob(os.path.join(lit_dir, "*.json")):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        pmids.update(str(p.get("pmid", "")) for p in data.get("papers", []) if p.get("pmid"))
    return pmids


def find_orphans(citations, lit_dir):
    """Return cited PMIDs missing from the corresponding lit json."""
    orphans = []
    union_pmids = None
    for symbol in sorted(citations, key=lambda s: "" if s is None else s):
        cited = citations[symbol]
        if symbol is None:
            if union_pmids is None:
                union_pmids = _all_lit_pmids(lit_dir)
            known = union_pmids
            reason = "not-in-lit"
        else:
            known = lit_pmids(lit_dir, symbol)
            reason = "no-lit-file" if known is None else "not-in-lit"
            if known is None:
                known = set()
        for pmid in sorted(cited):
            if pmid not in known:
                orphans.append((symbol, pmid, reason))
    return orphans


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--review", required=True, help="path to gene_literature_review.md")
    ap.add_argument("--lit-dir", help="default: lit/ next to --review")
    args = ap.parse_args()

    lit_dir = args.lit_dir or os.path.join(os.path.dirname(args.review) or ".", "lit")
    with open(args.review, encoding="utf-8") as f:
        citations = extract_citations(f.read())
    orphans = find_orphans(citations, lit_dir)
    n_checked = sum(len(pmids) for pmids in citations.values())

    for symbol, pmid, reason in orphans:
        print(f"ORPHAN {symbol}: PMID {pmid} not in lit ({reason})", file=sys.stderr)
    print(f"{n_checked} citations checked, {len(orphans)} orphan(s)")
    raise SystemExit(1 if orphans else 0)


if __name__ == "__main__":
    main()
