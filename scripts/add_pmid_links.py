#!/usr/bin/env python3
# ============================================================================
# add_pmid_links.py
# ============================================================================
# Author:      yjkim
# Purpose:     Fill deterministic PubMed links in review markdown.
# Description: Replaces each per-gene "근거 논문 전체 보기" line using only the
#              PMIDs already present in that gene's evidence table.
#              This script is stdlib-only and performs no network access.
# ============================================================================
import argparse
import re
import tempfile


HEADER_RE = re.compile(r"^###\s+(\S+)")
URL_RE = re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)")
TOKEN = "@@PMIDLINK@@"
LINK_LABEL = "근거 논문 전체 보기"


def pmid_link(pmids):
    if not pmids:
        return "(문헌 없음)"
    return "[PubMed에서 열기](https://pubmed.ncbi.nlm.nih.gov/?term=" + "+".join(pmids) + ")"


def substitute(review_path):
    with open(review_path, encoding="utf-8") as handle:
        lines = handle.readlines()

    count = 0
    section_pmids = []
    output_lines = []

    for line in lines:
        if HEADER_RE.match(line):
            section_pmids = []

        if LINK_LABEL in line or TOKEN in line:
            prefix = line.split(":", 1)[0]
            line = f"{prefix}: {pmid_link(section_pmids)}\n"
            count += 1
        else:
            for pmid in URL_RE.findall(line):
                if pmid not in section_pmids:
                    section_pmids.append(pmid)

        output_lines.append(line)

    with open(review_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.writelines(output_lines)

    return count


def selftest():
    with tempfile.NamedTemporaryFile("w+", encoding="utf-8", suffix=".md", delete=False) as handle:
        handle.write(
            "### FLG2 - filaggrin 2\n"
            "- **키워드와의 연관성**: claim [PMID:111]\n"
            "| PMID | 연도 | 접근수준 | 한 줄 요지 |\n"
            "|---|---:|---|---|\n"
            "| [222](https://pubmed.ncbi.nlm.nih.gov/222/) | 2022 | full-text | used |\n"
            "| [333](https://pubmed.ncbi.nlm.nih.gov/333/) | 2023 | full-text | used |\n"
            "- **근거 논문 전체 보기**: @@PMIDLINK@@\n"
        )
        path = handle.name

    count = substitute(path)
    with open(path, encoding="utf-8") as handle:
        result = handle.read()

    assert count == 1
    assert "?term=222+333" in result
    assert "111" not in result.split("근거 논문 전체 보기", 1)[1]
    assert TOKEN not in result
    print("ok: add_pmid_links self-checks pass")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--review")
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

    count = substitute(args.review)
    print(f"substituted {count} PubMed link(s)")


if __name__ == "__main__":
    main()
