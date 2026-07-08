#!/usr/bin/env python3
# ============================================================================
# ot_complement.py
# ============================================================================
# Author:      yjkim
# Purpose:     Select OpenTargets-supported genes missed by literature top-N.
# Description: Reads full OpenTargets scores and genes.tsv, then emits targets
#              absent from the final literature list but passing OpenTargets
#              genetic or clinical score thresholds.
#              This module is stdlib-only and has no ranking responsibility.
# ============================================================================
import argparse
import csv
import json
import os
import sys
import tempfile


OUT_COLS = ["symbol", "ot_genetic", "ot_clinical"]


def parse_score(value):
    if value == "":
        return 0.0
    return float(value)


def read_rows(path):
    with open(path, encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def select_complement(ot_rows, final_rows, min_clinical, min_genetic, top_k):
    final_symbols = {row["symbol"] for row in final_rows}
    selected = []
    for row in ot_rows:
        symbol = row["symbol"]
        genetic = parse_score(row.get("ot_genetic", ""))
        clinical = parse_score(row.get("ot_clinical", ""))
        if symbol in final_symbols:
            continue
        if clinical > min_clinical or genetic >= min_genetic:
            selected.append({
                "symbol": symbol,
                "ot_genetic": genetic,
                "ot_clinical": clinical,
            })

    return sorted(
        selected,
        key=lambda row: (-row["ot_genetic"], -row["ot_clinical"], row["symbol"]),
    )[:top_k]


def write_tsv(rows, out):
    writer = csv.writer(out, delimiter="\t", lineterminator="\n")
    writer.writerow(OUT_COLS)
    for row in rows:
        writer.writerow([
            row["symbol"],
            f"{row['ot_genetic']:.3f}",
            f"{row['ot_clinical']:.3f}",
        ])


def write_json(rows, out):
    json.dump(
        [
            {
                "symbol": row["symbol"],
                "ot_genetic": row["ot_genetic"],
                "ot_clinical": row["ot_clinical"],
            }
            for row in rows
        ],
        out,
    )
    out.write("\n")


def write_fixture(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUT_COLS, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def run_selftest():
    class Buffer:
        def __init__(self):
            self.value = ""

        def write(self, text):
            self.value += text

    with tempfile.TemporaryDirectory() as tmp_dir:
        ot_scores = os.path.join(tmp_dir, "ot_scores.tsv")
        final = os.path.join(tmp_dir, "genes.tsv")

        ot_rows = [
            {"symbol": "FINALHIGH", "ot_genetic": "0.900", "ot_clinical": "0.900"},
            {"symbol": "CLINICAL", "ot_genetic": "", "ot_clinical": "0.100"},
            {"symbol": "GENETIC", "ot_genetic": "0.500", "ot_clinical": ""},
            {"symbol": "CLINHIGH", "ot_genetic": "", "ot_clinical": "0.996"},
            {"symbol": "GENLOWCLIN", "ot_genetic": "0.001", "ot_clinical": "0.100"},
            {"symbol": "LOW", "ot_genetic": "0.499", "ot_clinical": "0.000"},
            {"symbol": "CLINBOUND", "ot_genetic": "", "ot_clinical": "0.000"},
            {"symbol": "SORTFIRST", "ot_genetic": "0.800", "ot_clinical": ""},
            {"symbol": "TIEA", "ot_genetic": "0.700", "ot_clinical": ""},
            {"symbol": "TIEB", "ot_genetic": "0.700", "ot_clinical": ""},
            {"symbol": "EXTRA1", "ot_genetic": "0.690", "ot_clinical": ""},
            {"symbol": "EXTRA2", "ot_genetic": "0.680", "ot_clinical": ""},
        ]
        final_rows = [
            {"symbol": "FINALHIGH", "ot_genetic": "0.900", "ot_clinical": "0.900"},
        ]
        write_fixture(ot_scores, ot_rows)
        write_fixture(final, final_rows)

        selected = select_complement(
            read_rows(ot_scores),
            read_rows(final),
            min_clinical=0.0,
            min_genetic=0.5,
            top_k=20,
        )
        symbols = [row["symbol"] for row in selected]
        assert "FINALHIGH" not in symbols
        assert "CLINICAL" in symbols
        assert "GENETIC" in symbols
        assert "LOW" not in symbols
        assert "CLINBOUND" not in symbols
        assert symbols.index("GENLOWCLIN") < symbols.index("CLINHIGH")
        assert symbols[:3] == ["SORTFIRST", "TIEA", "TIEB"]

        top_selected = select_complement(
            read_rows(ot_scores),
            read_rows(final),
            min_clinical=0.0,
            min_genetic=0.5,
            top_k=3,
        )
        assert [row["symbol"] for row in top_selected] == ["SORTFIRST", "TIEA", "TIEB"]
        assert len(top_selected) == 3

        stdout = sys.stdout
        try:
            buffer = Buffer()
            sys.stdout = buffer
            assert main([
                "--ot-scores", os.path.join(tmp_dir, "missing.tsv"),
                "--final", final,
                "--format", "json",
            ]) == 0
            assert buffer.value == "[]\n"
        finally:
            sys.stdout = stdout

    print("ok: ot_complement self-checks pass")


def parse_args(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--ot-scores")
    parser.add_argument("--final")
    parser.add_argument("--min-clinical", type=float, default=0.0)
    parser.add_argument("--min-genetic", type=float, default=0.5)
    parser.add_argument("--top-k", type=int, default=15)
    parser.add_argument("--format", choices=["tsv", "json"], default="tsv")
    parser.add_argument("--selftest", action="store_true")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv or sys.argv[1:])
    if args.selftest:
        run_selftest()
        return 0
    if not args.ot_scores or not args.final:
        raise SystemExit("--ot-scores and --final are required unless --selftest is set")
    if not os.path.exists(args.ot_scores):
        if args.format == "json":
            write_json([], sys.stdout)
        else:
            write_tsv([], sys.stdout)
        return 0

    selected = select_complement(
        read_rows(args.ot_scores),
        read_rows(args.final),
        args.min_clinical,
        args.min_genetic,
        args.top_k,
    )
    if args.format == "json":
        write_json(selected, sys.stdout)
    else:
        write_tsv(selected, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
