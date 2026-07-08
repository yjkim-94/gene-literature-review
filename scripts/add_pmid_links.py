#!/usr/bin/env python3
# ============================================================================
# add_pmid_links.py
# ============================================================================
# Author:      yjkim
# Purpose:     Fill deterministic PubMed 전체보기 links in review markdown.
# Description: Replaces @@PMIDLINK@@ tokens inside per-gene markdown blocks
#              using PMIDs from lit/<SYMBOL>.json files.
#              This script is stdlib-only and performs no network access.
# ============================================================================
import argparse
import json
import os
import re
import sys
import tempfile


HEADER_RE = re.compile(r"^###\s+(\S+)")
TOKEN = "@@PMIDLINK@@"


def pmid_link(lit_dir, symbol):
    path = os.path.join(lit_dir, f"{symbol}.json")
    if not os.path.exists(path):
        return "(문헌 없음)"

    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)

    pmids = []
    for paper in data.get("papers", []):
        pmid = re.sub(r"\D", "", str(paper.get("pmid", "")))
        if pmid:
            pmids.append(pmid)

    if not pmids:
        return "(문헌 없음)"

    return "[PubMed에서 열기](https://pubmed.ncbi.nlm.nih.gov/?term=" + "+".join(pmids) + ")"


def substitute(review_path, lit_dir):
    with open(review_path, encoding="utf-8") as handle:
        lines = handle.readlines()

    current_symbol = None
    count = 0
    output_lines = []

    for line in lines:
        match = HEADER_RE.match(line)
        if match:
            current_symbol = match.group(1)

        if TOKEN in line:
            if current_symbol is None:
                print(f"warning: {TOKEN} before any ### header", file=sys.stderr)
            else:
                line = line.replace(TOKEN, pmid_link(lit_dir, current_symbol))
                count += 1

        output_lines.append(line)

    with open(review_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.writelines(output_lines)

    return count


def selftest():
    with tempfile.TemporaryDirectory() as tmp_dir:
        review_path = os.path.join(tmp_dir, "gene_literature_review.md")
        lit_dir = os.path.join(tmp_dir, "lit")
        os.makedirs(lit_dir)

        with open(review_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(
                "### IL31 — interleukin 31\n"
                "- **근거 논문 전체 보기**: @@PMIDLINK@@\n"
                "### TNF — tumor necrosis factor\n"
                "- **근거 논문 전체 보기**: @@PMIDLINK@@\n"
                "### EMPTY — empty gene\n"
                "- **근거 논문 전체 보기**: @@PMIDLINK@@\n"
            )

        fixtures = {
            "IL31": {"symbol": "IL31", "papers": [{"pmid": "34106037"}, {"pmid": "30194992"}]},
            "TNF": {"symbol": "TNF", "papers": [{"pmid": "PMID 1"}, {"pmid": "2"}]},
            "EMPTY": {"symbol": "EMPTY", "papers": []},
        }
        for symbol, data in fixtures.items():
            with open(os.path.join(lit_dir, f"{symbol}.json"), "w", encoding="utf-8", newline="\n") as handle:
                json.dump(data, handle)

        count = substitute(review_path, lit_dir)
        with open(review_path, encoding="utf-8") as handle:
            result = handle.read()

        assert count == 3
        assert "?term=34106037+30194992" in result
        assert "?term=1+2" in result
        assert "(문헌 없음)" in result
        assert TOKEN not in result

    print("ok: add_pmid_links self-checks pass")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--review")
    parser.add_argument("--lit")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()

    if not args.selftest and not args.review:
        parser.error("--review is required unless --selftest")

    return args


def main():
    args = parse_args()
    if args.selftest:
        selftest()
        return

    lit_dir = args.lit or os.path.join(os.path.dirname(args.review), "lit")
    count = substitute(args.review, lit_dir)
    print(f"substituted {count} PubMed link(s)")


if __name__ == "__main__":
    main()
