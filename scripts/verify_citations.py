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
            citations.setdefault(symbol, set())
        elif line.startswith("## "):
            symbol = None
        pmids = set(PMID_RE.findall(line)) | set(URL_RE.findall(line))
        if pmids:
            citations.setdefault(symbol, set()).update(pmids)
    return citations


def section_errors(md_text, lit_dir):
    """Return section-level citation and no-literature consistency errors."""
    sections = {}
    symbol = None
    for line in md_text.splitlines():
        match = HEADER_RE.match(line)
        if match:
            symbol = match.group(1)
            sections.setdefault(symbol, [])
        elif line.startswith("## "):
            symbol = None
        elif symbol is not None:
            sections[symbol].append(line)

    errors = []
    for symbol, lines in sections.items():
        path = os.path.join(lit_dir, f"{symbol}.json")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            papers = json.load(f).get("papers", [])
        text = "\n".join(lines)
        citations = extract_citations(f"### {symbol}\n{text}").get(symbol, set())
        if papers and not citations:
            errors.append(f"NO_CITATIONS {symbol}")
        if papers and "관련 문헌 없음" in text:
            errors.append(f"FALSE_NO_LITERATURE {symbol}")
    return errors


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
        md_text = f.read()
    citations = extract_citations(md_text)
    orphans = find_orphans(citations, lit_dir)
    errors = section_errors(md_text, lit_dir)
    n_checked = sum(len(pmids) for pmids in citations.values())

    for symbol, pmid, reason in orphans:
        print(f"ORPHAN {symbol}: PMID {pmid} not in lit ({reason})", file=sys.stderr)
    for error in errors:
        print(error, file=sys.stderr)
    print(f"{n_checked} citations checked, {len(orphans)} orphan(s)")
    raise SystemExit(1 if orphans or errors else 0)


if __name__ == "__main__":
    main()
