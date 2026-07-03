#!/usr/bin/env python3
"""Quantitative eval: gene-list recall against curated gold sets.

Runs fetch_genes for each eval keyword and reports what fraction of the
curated canonical genes appear in the returned top-N list. This is the part of
the skill worth measuring automatically -- summary prose is judged by a human.
"""
import csv
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FETCH = os.path.join(HERE, "..", "scripts", "fetch_genes.py")


def run_one(keyword, gold, top_n, scan):
    out = os.path.join(tempfile.gettempdir(), f"eval_{keyword}.tsv")
    subprocess.run([sys.executable, FETCH, "--keyword", keyword, "--organism",
                    "human", "--max", str(top_n), "--scan", str(scan),
                    "--out", out],
                   check=True, stderr=subprocess.DEVNULL)
    with open(out, encoding="utf-8", newline="") as f:
        got = [row["symbol"] for row in csv.DictReader(f, delimiter="\t")]
    hits = [g for g in gold if g in got]
    return got, hits


def main():
    evals = json.load(open(os.path.join(HERE, "evals.json"), encoding="utf-8"))["evals"]
    top_n, scan = 20, 80
    rows = []
    for e in evals:
        gold = e["gold_genes"]
        got, hits = run_one(e["keyword"], gold, top_n, scan)
        recall = len(hits) / len(gold)
        rows.append((e["keyword"], recall, hits, got[:top_n]))
        print(f"\n[{e['keyword']}] recall@{top_n} = {recall:.2f} ({len(hits)}/{len(gold)})")
        print(f"  hit : {hits}")
        print(f"  miss: {[g for g in gold if g not in hits]}")
        print(f"  top : {got[:12]}")
    mean = sum(r[1] for r in rows) / len(rows)
    print(f"\n=== mean recall@{top_n} = {mean:.2f} ===")


if __name__ == "__main__":
    main()
