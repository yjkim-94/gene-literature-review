#!/usr/bin/env python3
"""Offline regression test for verify_citations."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from verify_citations import extract_citations, find_orphans


def write_lit(path, symbol, pmids):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {"symbol": symbol, "name": symbol.lower(), "papers": [{"pmid": p} for p in pmids]},
            f,
        )


def test_orphan_detection():
    with tempfile.TemporaryDirectory() as d:
        lit_dir = os.path.join(d, "lit")
        os.makedirs(lit_dir)
        write_lit(os.path.join(lit_dir, "GENEA.json"), "GENEA", ["111", "222"])
        md = (
            "### GENEA — gene a\n"
            "text [PMID:111] and [222](https://pubmed.ncbi.nlm.nih.gov/222/)\n"
            "### GENEB — gene b\n"
            "text [PMID:999]\n"
        )
        citations = extract_citations(md)
        assert citations["GENEA"] == {"111", "222"}, citations
        assert citations["GENEB"] == {"999"}, citations
        assert find_orphans(citations, lit_dir) == [("GENEB", "999", "no-lit-file")]


def test_clean_case():
    with tempfile.TemporaryDirectory() as d:
        lit_dir = os.path.join(d, "lit")
        os.makedirs(lit_dir)
        write_lit(os.path.join(lit_dir, "GENEA.json"), "GENEA", ["111", "222"])
        md = (
            "### GENEA — gene a\n"
            "text [PMID:111] and [222](https://pubmed.ncbi.nlm.nih.gov/222/)\n"
        )
        assert find_orphans(extract_citations(md), lit_dir) == []


if __name__ == "__main__":
    test_orphan_detection()
    test_clean_case()
    print("ok: citation PMIDs are verified against lit json files")
