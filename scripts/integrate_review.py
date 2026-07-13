#!/usr/bin/env python3
# ============================================================================
# integrate_review.py
# ============================================================================
# Author:      yjkim
# Purpose:     Assemble a gene literature review Markdown document.
# Description: Reads genes.tsv, Phase 3 batch summaries, lit JSON files, and
#              optional OpenTargets scores from one run directory.
# ============================================================================
import argparse
import csv
import json
import pathlib
import re
import subprocess
import sys
import tempfile
from datetime import datetime


HEADER_RE = re.compile(r"^###\s+(\S+)")
RELATION_RE = re.compile(r"\*\*키워드와의 연관성\*\*:\s*(.+)")
PMID_RE = re.compile(r"\s*\[PMID:\d+\]")


def read_genes(run_dir):
    with (run_dir / "genes.tsv").open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def read_lit(run_dir, symbol):
    path = run_dir / "lit" / f"{symbol}.json"
    if not path.exists():
        return {"papers": []}
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def read_summaries(summary_dir):
    chunks = [
        path.read_text(encoding="utf-8").lstrip("\ufeff").strip()
        for path in sorted(summary_dir.glob("batch[0-9][0-9].md"))
    ]
    if not chunks:
        raise SystemExit(f"no batch summaries found: {summary_dir}")
    return "\n\n".join(chunks).strip() + "\n"


def first_relation(summary_text, symbol):
    pattern = re.compile(
        rf"^###\s+{re.escape(symbol)}\b.*?(?=^###\s+\S+|\Z)",
        re.S | re.M,
    )
    match = pattern.search(summary_text)
    if not match:
        return "요약 없음"

    block = match.group(0)
    relation = RELATION_RE.search(block)
    if not relation:
        return "관련 문헌 없음" if "관련 문헌 없음" in block else "요약 없음"

    line = PMID_RE.sub("", relation.group(1).strip())
    first_sentence = line.split(".")[0].strip()
    return f"{first_sentence}." if first_sentence else "요약 없음"


def ot_complement_rows(run_dir, helper):
    ot_scores = run_dir / "ot_scores.tsv"
    if not ot_scores.exists() or not helper.exists():
        return []

    proc = subprocess.run(
        [
            sys.executable,
            str(helper),
            "--ot-scores",
            str(ot_scores),
            "--final",
            str(run_dir / "genes.tsv"),
        ],
        check=True,
        text=True,
        capture_output=True,
        encoding="utf-8",
    )
    return [
        line.split("\t")
        for line in proc.stdout.strip().splitlines()[1:]
        if line.strip()
    ]


def fmt_score(value):
    return value if value else "-"


def collection_date(run_dir):
    paths = list((run_dir / "lit").glob("*.json"))
    if not paths:
        return "-"
    latest = max(path.stat().st_mtime for path in paths)
    return datetime.fromtimestamp(latest).date().isoformat()


def build_review(run_dir, keyword, organism, summary_dir, ot_helper):
    genes = read_genes(run_dir)
    summaries = read_summaries(summary_dir)
    table_lines = []
    total_papers = 0

    for row in genes:
        symbol = row["symbol"]
        papers = read_lit(run_dir, symbol).get("papers", [])
        total_papers += len(papers)
        years = [
            int(paper["year"])
            for paper in papers
            if str(paper.get("year", "")).isdigit()
        ]
        table_lines.append(
            "| {symbol} | {relation} | {n} | {year} | {otg} | {otc} |".format(
                symbol=symbol,
                relation=first_relation(summaries, symbol).replace("|", "/"),
                n=len(papers),
                year=max(years) if years else "-",
                otg=fmt_score(row.get("ot_genetic", "")),
                otc=fmt_score(row.get("ot_clinical", "")),
            )
        )

    comp_lines = [
        f"| {symbol} | {ot_genetic} | {ot_clinical} |"
        for symbol, ot_genetic, ot_clinical in ot_complement_rows(run_dir, ot_helper)
    ]

    doc = [
        f"# {keyword} 관련 Gene 문헌 조사\n",
        "## 요약 (한눈에 보기)\n",
        "| Gene | 키워드 연관성(요약) | 근거 논문 수 | 최신 연도 | OT유전 | OT임상 |",
        "|------|----------------------|-------------|----------|--------|--------|",
        *table_lines,
        (
            "> OT유전/OT임상 = OpenTargets DB 점수"
            "(문헌 근거 아님, 참고용). 값은 genes.tsv의 "
            "ot_genetic/ot_clinical이며, 없으면 '-'입니다.\n"
        ),
        "## Gene별 상세\n",
        summaries,
    ]

    if comp_lines:
        doc.extend([
            "## OpenTargets 교차참조 (문헌 근거 아님)\n",
            (
                "> OpenTargets DB가 유전/임상 근거로 지목하지만 현재 "
                "문헌 상위 목록에는 없는 대상입니다. 후속 조사 lead로만 "
                "사용하고 PMID citation과 섞지 않습니다.\n"
            ),
            "| Gene | OT유전 | OT임상 |",
            "|------|--------|--------|",
            *comp_lines,
            "",
        ])

    doc.extend([
        "## 방법\n",
        f'- Gene 목록: PubTator3 NER + NCBI Gene, keyword="{keyword}", organism={organism}, N={len(genes)}',
        (
            "- 문헌: PubMed E-utilities, gene별 상위 논문 수집, "
            f"수집일 {collection_date(run_dir)}, 근거 논문 {total_papers}개"
        ),
        (
            "- 접근수준: full-text=PMC 무료 full text 이용 가능"
            "(요약은 abstract 기준), abstract-only=abstract만 공개"
        ),
        (
            "- 철회 논문: PubMed가 Retracted Publication으로 표시한 논문은 "
            "철회로 표시하고 근거에서 제외"
        ),
        (
            "- OpenTargets overlay: genetic/clinical 점수는 DB 교차참조이며 "
            "문헌 evidence 또는 ranking 기준이 아님"
        ),
        (
            "- 인용 검증: verify_citations.py로 모든 PMID가 수집 JSON에 "
            "존재하는지 기계적으로 대조"
        ),
        (
            "- 주의: spec_adj는 keyword 맥락에서 얼마나 함께 연구되는지의 "
            "지표이며 causal association 증명이 아님. 최종 해석은 abstract "
            "근거 확인이 필요함.\n"
        ),
    ])
    return "\n".join(doc)


def selftest():
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = pathlib.Path(tmp) / "output" / "demo"
        summary_dir = run_dir / "summaries"
        lit_dir = run_dir / "lit"
        summary_dir.mkdir(parents=True)
        lit_dir.mkdir()
        (run_dir / "genes.tsv").write_text(
            "symbol\tot_genetic\tot_clinical\nIL31\t0.100\t\n",
            encoding="utf-8",
            newline="\n",
        )
        (lit_dir / "IL31.json").write_text(
            json.dumps({"papers": [{"pmid": "1", "year": "2024"}]}),
            encoding="utf-8",
            newline="\n",
        )
        (summary_dir / "batch01.md").write_text(
            "\ufeff### IL31 - interleukin 31\n"
            "- **키워드와의 연관성**: IL31은 AD itch와 연결된다 [PMID:1].\n",
            encoding="utf-8",
            newline="\n",
        )
        review = build_review(run_dir, "demo keyword", "human", summary_dir, pathlib.Path("missing.py"))
        assert "# demo keyword 관련 Gene 문헌 조사" in review
        assert "| IL31 | IL31은 AD itch와 연결된다. | 1 | 2024 | 0.100 | - |" in review
        assert "OpenTargets 교차참조" not in review
    print("ok: integrate_review self-checks pass")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", help="Run directory, e.g. output/<slug>")
    parser.add_argument("--keyword", help="Display keyword. Default: run-dir name with '-' replaced by spaces.")
    parser.add_argument("--organism", default="human")
    parser.add_argument("--summaries", help="Default: <run-dir>/summaries")
    parser.add_argument("--out", help="Default: <run-dir>/gene_literature_review.md")
    parser.add_argument("--ot-helper", help="Default: scripts/ot_complement.py next to this script")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if not args.selftest and not args.run_dir:
        parser.error("--run-dir is required unless --selftest")
    return args


def main():
    args = parse_args()
    if args.selftest:
        selftest()
        return

    run_dir = pathlib.Path(args.run_dir)
    keyword = args.keyword or run_dir.name.replace("-", " ")
    summary_dir = pathlib.Path(args.summaries) if args.summaries else run_dir / "summaries"
    out = pathlib.Path(args.out) if args.out else run_dir / "gene_literature_review.md"
    ot_helper = pathlib.Path(args.ot_helper) if args.ot_helper else pathlib.Path(__file__).with_name("ot_complement.py")

    out.write_text(
        build_review(run_dir, keyword, args.organism, summary_dir, ot_helper),
        encoding="utf-8",
        newline="\n",
    )
    print(out)


if __name__ == "__main__":
    main()
