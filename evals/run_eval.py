#!/usr/bin/env python3
"""Quantitative eval: gene-list recall against curated gold sets.

Runs fetch_genes for each eval keyword and reports what fraction of the
curated canonical genes appear in the returned top-N list. This is the part of
the skill worth measuring automatically -- summary prose is judged by a human.
"""
import csv
import argparse
import json
import os
import subprocess
import sys
import tempfile
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
FETCH = os.path.join(HERE, "..", "scripts", "fetch_genes.py")


def read_symbols(path):
    with open(path, encoding="utf-8", newline="") as f:
        return [row["symbol"] for row in csv.DictReader(f, delimiter="\t")]


def read_scored_rows(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def run_one(eval_case, top_n, scan):
    keyword = eval_case["keyword"]
    top_n = eval_case.get("max", top_n)
    scan = eval_case.get("scan", scan)
    out = os.path.join(tempfile.gettempdir(), f"eval_{keyword}.tsv")
    cmd = [sys.executable, FETCH, "--keyword", keyword, "--organism",
           "human", "--max", str(top_n), "--scan", str(scan), "--out", out]
    if eval_case.get("entity"):
        cmd += ["--entity", eval_case["entity"]]
    subprocess.run(cmd, check=True)
    got = read_symbols(out)
    root, ext = os.path.splitext(out)
    all_scored = read_scored_rows(f"{root}_all_scored{ext or '.tsv'}")
    return got, all_scored


def summarize(keyword, gold, got, all_scored, top_n):
    got_rank = {symbol: i + 1 for i, symbol in enumerate(got)}
    scored_rank = {row["symbol"]: i + 1 for i, row in enumerate(all_scored)}
    scored_by_symbol = {row["symbol"]: row for row in all_scored}
    hits_top = [g for g in gold if g in got_rank and got_rank[g] <= top_n]
    hits10 = [g for g in gold if g in got_rank and got_rank[g] <= 10]
    ranks = [got_rank[g] for g in hits_top]
    misses = []
    for gene in gold:
        if gene in hits_top:
            continue
        if gene not in scored_by_symbol:
            misses.append((gene, "pool-miss", "not in genes_all_scored.tsv"))
            continue
        row = scored_by_symbol[gene]
        detail = (f"all_rank={scored_rank[gene]}, spec_adj={row['spec_adj']}, "
                  f"co={row['co_papers']}/{row['gene_papers']}, "
                  f"below_floor={row['below_floor']}")
        misses.append((gene, "rank-cut", detail))
    rank_summary = "NA"
    if ranks:
        rank_summary = (f"median={statistics.median(ranks):.1f}, "
                        f"mean={statistics.mean(ranks):.1f}")
    return {
        "keyword": keyword,
        "recall10": len(hits10) / len(gold),
        "recall_top": len(hits_top) / len(gold),
        "hits10": hits10,
        "hits_top": hits_top,
        "misses": misses,
        "ranks": ranks,
        "rank_summary": rank_summary,
    }


def print_result(result, gold, got, top_n):
    print(f"\n[{result['keyword']}]")
    print(f"  recall@10 = {result['recall10']:.2f} "
          f"({len(result['hits10'])}/{len(gold)})")
    print(f"  recall@{top_n} = {result['recall_top']:.2f} "
          f"({len(result['hits_top'])}/{len(gold)})")
    print(f"  gold rank summary: {result['rank_summary']}")
    print(f"  hit@{top_n} : {result['hits_top']}")
    print(f"  miss  : {[m[0] for m in result['misses']]}")
    for gene, reason, detail in result["misses"]:
        print(f"    - {gene}: {reason} ({detail})")
    print(f"  top : {got[:12]}")


def write_markdown(path, rows, top_n):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"# Recall eval results\n\n")
        f.write(f"| keyword | recall@10 | recall@{top_n} | rank summary | miss |\n")
        f.write("|---|---:|---:|---|---|\n")
        for row in rows:
            miss = ", ".join(g for g, _, _ in row["misses"]) or "none"
            f.write(
                f"| {row['keyword']} | {row['recall10']:.2f} | "
                f"{row['recall_top']:.2f} | {row['rank_summary']} | {miss} |\n"
            )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max", type=int, default=30)
    parser.add_argument("--scan", type=int, default=500)
    parser.add_argument("--config", default=os.path.join(HERE, "evals.json"))
    parser.add_argument("--out-md", default=os.path.join(HERE, "output", "recall_eval.md"))
    args = parser.parse_args()

    evals = json.load(open(args.config, encoding="utf-8"))["evals"]
    rows = []
    for e in evals:
        gold = e["gold_genes"]
        got, all_scored = run_one(e, args.max, args.scan)
        result = summarize(e["keyword"], gold, got, all_scored, args.max)
        rows.append(result)
        print_result(result, gold, got, args.max)
    mean = sum(r["recall_top"] for r in rows) / len(rows)
    print(f"\n=== mean recall@{args.max} = {mean:.2f} ===")
    write_markdown(args.out_md, rows, args.max)
    print(f"-> {args.out_md}")


if __name__ == "__main__":
    main()
