#!/usr/bin/env python3
"""Offline regression test for verify_citations."""
import json
import os
import sys
import tempfile
from contextlib import redirect_stderr
from io import StringIO

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verify_citations
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


def run_main(review, lit_dir):
    stderr = StringIO()
    argv = sys.argv
    sys.argv = ["verify_citations.py", "--review", review, "--lit-dir", lit_dir]
    try:
        with redirect_stderr(stderr):
            try:
                verify_citations.main()
            except SystemExit as exc:
                return exc.code, stderr.getvalue()
    finally:
        sys.argv = argv


def test_section_errors():
    with tempfile.TemporaryDirectory() as d:
        lit_dir = os.path.join(d, "lit")
        os.makedirs(lit_dir)
        review = os.path.join(d, "review.md")

        write_lit(os.path.join(lit_dir, "GENEA.json"), "GENEA", ["111"])
        with open(review, "w", encoding="utf-8", newline="\n") as f:
            f.write("### GENEA\ntext without citation\n")
        code, stderr = run_main(review, lit_dir)
        assert code == 1 and "NO_CITATIONS GENEA" in stderr, stderr

        with open(review, "w", encoding="utf-8", newline="\n") as f:
            f.write("### GENEA\n관련 문헌 없음 [PMID:111]\n")
        code, stderr = run_main(review, lit_dir)
        assert code == 1 and "FALSE_NO_LITERATURE GENEA" in stderr, stderr

        write_lit(os.path.join(lit_dir, "GENEB.json"), "GENEB", [])
        with open(review, "w", encoding="utf-8", newline="\n") as f:
            f.write("### GENEB\n관련 문헌 없음\n")
        code, stderr = run_main(review, lit_dir)
        assert code == 0 and not stderr, stderr

        with open(review, "w", encoding="utf-8", newline="\n") as f:
            f.write("### GENEA\nsummary\n## 방법\n[PMID:111]\n")
        code, stderr = run_main(review, lit_dir)
        assert code == 1 and "NO_CITATIONS GENEA" in stderr, stderr


if __name__ == "__main__":
    test_orphan_detection()
    test_clean_case()
    test_section_errors()
    print("ok: citation PMIDs are verified against lit json files")
