#!/usr/bin/env python3
# ============================================================================
# candidate_c_bench.py
# ============================================================================
# Author:      yjkim
# Purpose:     Benchmark OpenTargets genetic ranking against literature ranking.
# Description: Compares spec_adj_artifact and OpenTargets genetic_association
#              rankings against OpenTargets clinical targets as known-drug gold.
#              Writes a cross-disease markdown summary under evals/output/.
# Usage:       python evals/candidate_c_bench.py [--refresh-gt] [--selftest]
# ============================================================================
import argparse
import json
import os
import sys
import traceback


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from cdrs_bench import (  # noqa: E402
    auprc,
    compute_rankings,
    disease_total_from_pubtator,
    ensure_scored,
    load_scored,
    ndcg_at_k,
    precision_at_k,
)
from ground_truth import load_ground_truth  # noqa: E402


RANKING_ORDER = ("lit", "ot_genetic")
METRIC_ORDER = ("P@10", "P@20", "nDCG@20", "AUPRC")


# ============================================================================
# Evaluation
# ============================================================================
def score_ranking(ranked, gold):
    return {
        "P@10": precision_at_k(ranked, gold, 10),
        "P@20": precision_at_k(ranked, gold, 20),
        "nDCG@20": ndcg_at_k(ranked, gold, 20),
        "AUPRC": auprc(ranked, gold),
    }


def evaluate(disease, refresh_gt=False):
    scored_path = ensure_scored(disease)
    rows, warnings = load_scored(scored_path)
    disease_total = disease_total_from_pubtator(disease)
    lit_ranking = compute_rankings(rows, disease_total)["spec_adj_artifact"]
    gt = load_ground_truth(
        disease["mondo_id"],
        disease["genetic_threshold"],
        refresh=refresh_gt,
    )
    ot_genetic_full = [
        symbol for symbol, _ in sorted(
            gt["genetic_all"].items(),
            key=lambda kv: (kv[1], kv[0]),
            reverse=True,
        )
    ]
    candidates = {row["symbol"] for row in rows}
    gold = gt["clinical"]

    lit_restricted = [gene for gene in lit_ranking if gene in candidates]
    ot_restricted = [gene for gene in ot_genetic_full if gene in candidates]
    gold_c = gold & candidates
    scores = {
        "lit": score_ranking(lit_restricted, gold_c),
        "ot_genetic": score_ranking(ot_restricted, gold_c),
    }

    lit_top = lit_ranking[:20]
    ot_top = ot_genetic_full[:20]
    measurement_b = {
        "gold_hits_lit": sorted(set(lit_top) & gold),
        "gold_hits_ot": sorted(set(ot_top) & gold),
        "ot_only": sorted((set(ot_top) & gold) - set(lit_top)),
        "lit_only": sorted((set(lit_top) & gold) - set(ot_top)),
    }

    return {
        "disease": disease,
        "scores": scores,
        "measurement_b": measurement_b,
        "warnings": warnings,
        "gt_error": gt.get("error"),
        "meta": {
            "keyword": disease["keyword"],
            "n_gold": len(gold),
            "n_gold_in_candidates": len(gold_c),
        },
    }


def aggregate_scores(evaluations):
    eligible = [
        result for result in evaluations
        if result["meta"]["n_gold_in_candidates"] > 0
    ]
    skipped = [
        result["meta"]["keyword"] for result in evaluations
        if result["meta"]["n_gold_in_candidates"] <= 0
    ]
    means = {}
    for ranking in RANKING_ORDER:
        means[ranking] = {}
        for metric in METRIC_ORDER:
            values = [
                result["scores"][ranking][metric]
                for result in eligible
                if ranking in result["scores"]
            ]
            means[ranking][metric] = (
                sum(values) / len(values)
                if values else None
            )
    return {"means": means, "eligible": eligible, "skipped": skipped}


# ============================================================================
# Report
# ============================================================================
def _fmt_metric(value):
    return "NA" if value is None else f"{value:.3f}"


def _fmt_genes(genes):
    return ", ".join(genes) if genes else "-"


def render_summary(evaluations, errors=None):
    errors = errors or []
    aggregate = aggregate_scores(evaluations)
    lines = [
        "# Candidate C bench - OT genetic vs literature ranking",
        "",
        "Clinical gold is OpenTargets datatypeScores id `clinical` with score > 0.",
        "",
        "## Measurement A: same-universe ranking quality",
        "",
        "| disease | n_gold(clinical) | n_gold_in_candidates | ranking | P@10 | P@20 | nDCG@20 | AUPRC |",
        "|---------|------------------|----------------------|---------|------|------|---------|-------|",
    ]
    for result in evaluations:
        meta = result["meta"]
        for ranking in RANKING_ORDER:
            metric = result["scores"][ranking]
            lines.append(
                f"| {meta['keyword']} | {meta['n_gold']} | "
                f"{meta['n_gold_in_candidates']} | {ranking} | "
                f"{metric['P@10']:.3f} | {metric['P@20']:.3f} | "
                f"{metric['nDCG@20']:.3f} | {metric['AUPRC']:.3f} |"
            )

    lines.extend(
        [
            "",
            "## Measurement B: OT unrestricted complement",
            "",
            "| disease | lit_top20 clinical hits | ot_top20 clinical hits | ot_only | lit_only |",
            "|---------|-------------------------|------------------------|---------|----------|",
        ]
    )
    for result in evaluations:
        meta = result["meta"]
        measurement_b = result["measurement_b"]
        lines.append(
            f"| {meta['keyword']} | "
            f"{_fmt_genes(measurement_b['gold_hits_lit'])} | "
            f"{_fmt_genes(measurement_b['gold_hits_ot'])} | "
            f"{_fmt_genes(measurement_b['ot_only'])} | "
            f"{_fmt_genes(measurement_b['lit_only'])} |"
        )

    lines.extend(
        [
            "",
            "## Mean ranking metrics",
            "",
            "Averaged across diseases with at least one clinical gold-in-candidates.",
            "",
            "| ranking | mean P@10 | mean P@20 | mean nDCG@20 | mean AUPRC |",
            "|---------|-----------|-----------|--------------|------------|",
        ]
    )
    for ranking in RANKING_ORDER:
        metric = aggregate["means"][ranking]
        lines.append(
            f"| {ranking} | {_fmt_metric(metric['P@10'])} | "
            f"{_fmt_metric(metric['P@20'])} | "
            f"{_fmt_metric(metric['nDCG@20'])} | "
            f"{_fmt_metric(metric['AUPRC'])} |"
        )

    skipped = aggregate["skipped"]
    lines.extend(["", "## Skipped from mean", ""])
    if skipped:
        lines.extend(f"- {keyword}: no clinical gold-in-candidates" for keyword in skipped)
    else:
        lines.append("- none")

    lines.extend(["", "## Verdict", ""])
    eligible = aggregate["eligible"]
    if eligible:
        best_ndcg = max(
            RANKING_ORDER,
            key=lambda ranking: aggregate["means"][ranking]["nDCG@20"],
        )
        best_auprc = max(
            RANKING_ORDER,
            key=lambda ranking: aggregate["means"][ranking]["AUPRC"],
        )
        lines.append(
            f"Higher mean nDCG@20: {best_ndcg}; higher mean AUPRC: {best_auprc}."
        )
    else:
        lines.append("No disease had clinical gold-in-candidates; no mean verdict available.")

    lines.extend(
        [
            "",
            "## Caveat",
            "",
            "- Tuning set only.",
            "- Clinical gold is tiny for some diseases.",
            "- Directional benchmark only; not a significance test.",
        ]
    )
    gt_warnings = [
        result for result in evaluations
        if result.get("gt_error") or result.get("warnings")
    ]
    if gt_warnings:
        lines.extend(["", "## Warnings", ""])
        for result in gt_warnings:
            keyword = result["meta"]["keyword"]
            if result.get("gt_error"):
                lines.append(f"- {keyword}: {result['gt_error']}")
            for warning in result.get("warnings") or []:
                lines.append(f"- {keyword}: {warning}")
    if errors:
        lines.extend(["", "## Errors", ""])
        lines.extend(
            f"- {error['keyword']}: {error['error']}"
            for error in errors
        )
    return "\n".join(lines)


# ============================================================================
# Tests and CLI
# ============================================================================
def _selftest():
    candidates = {"A", "B", "C"}
    gold = {"A", "D"}
    lit_ranking = ["B", "A", "C", "D"]
    ot_genetic_full = ["D", "C", "A", "B"]
    lit_restricted = [gene for gene in lit_ranking if gene in candidates]
    ot_restricted = [gene for gene in ot_genetic_full if gene in candidates]
    gold_c = gold & candidates
    assert lit_restricted == ["B", "A", "C"]
    assert ot_restricted == ["C", "A", "B"]
    assert gold_c == {"A"}

    assert precision_at_k(["A", "B", "C"], gold_c, 1) == 1.0
    assert precision_at_k(["B", "A", "C"], gold_c, 2) == 0.5
    assert abs(auprc(["B", "A", "C"], gold_c) - 0.5) < 1e-9

    fake_evaluations = [
        {
            "scores": {
                "lit": {"P@10": 0.1, "P@20": 0.2, "nDCG@20": 0.3, "AUPRC": 0.4},
                "ot_genetic": {"P@10": 0.5, "P@20": 0.6, "nDCG@20": 0.7, "AUPRC": 0.8},
            },
            "measurement_b": {},
            "meta": {"keyword": "eligible", "n_gold": 2, "n_gold_in_candidates": 1},
        },
        {
            "scores": {
                "lit": {"P@10": 9.1, "P@20": 9.2, "nDCG@20": 9.3, "AUPRC": 9.4},
                "ot_genetic": {"P@10": 9.5, "P@20": 9.6, "nDCG@20": 9.7, "AUPRC": 9.8},
            },
            "measurement_b": {},
            "meta": {"keyword": "skipped", "n_gold": 2, "n_gold_in_candidates": 0},
        },
    ]
    aggregate = aggregate_scores(fake_evaluations)
    assert aggregate["skipped"] == ["skipped"]
    assert aggregate["means"]["lit"]["P@10"] == 0.1
    assert aggregate["means"]["ot_genetic"]["AUPRC"] == 0.8
    print("ok: candidate_c self-checks pass")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--refresh-gt",
        action="store_true",
        help="re-fetch OpenTargets gold; first run needs this to populate clinical cache",
    )
    parser.add_argument(
        "--heldout",
        action="store_true",
        help="use evals/bench_diseases_heldout.json instead of --config",
    )
    parser.add_argument(
        "--config",
        default=os.path.join(HERE, "bench_diseases.json"),
        help="disease config JSON (default: evals/bench_diseases.json)",
    )
    parser.add_argument("--selftest", action="store_true", help="run offline self-checks and exit")
    args = parser.parse_args()

    if args.selftest:
        _selftest()
        return

    config_path = args.config
    if args.heldout:
        config_path = os.path.join(HERE, "bench_diseases_heldout.json")

    with open(config_path, encoding="utf-8") as handle:
        config = json.load(handle)

    evaluations = []
    errors = []
    for disease in config["diseases"]:
        try:
            evaluations.append(evaluate(disease, refresh_gt=args.refresh_gt))
        except Exception as exc:
            print(
                f"ERROR: failed to evaluate '{disease['keyword']}': {exc}",
                file=sys.stderr,
            )
            traceback.print_exc()
            errors.append({"keyword": disease["keyword"], "error": str(exc)})

    summary = render_summary(evaluations, errors)
    out_dir = os.path.join(HERE, "output")
    os.makedirs(out_dir, exist_ok=True)
    summary_path = os.path.join(out_dir, "candidate_c_SUMMARY.md")
    with open(summary_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(summary + "\n")
    print(f"\n{summary}\n\n-> {summary_path}")


if __name__ == "__main__":
    main()
