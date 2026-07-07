#!/usr/bin/env python3
# ============================================================================
# cdrs_bench.py
# ============================================================================
# Author:      yjkim
# Purpose:     Benchmark CDRS ranking formulas against OpenTargets genetic gold.
# Description: Recomputes seven rankings offline from genes_all_scored.tsv columns
#              and scores each ranking with P@10, P@20, nDCG@20, and AUPRC.
#              CDRS weights are PLACEHOLDER values from method_dev_REFERENCE.md
#              and are intentionally labeled as such in the report.
# Usage:       python evals/cdrs_bench.py [--refresh-gt] [--selftest]
# ============================================================================
import argparse
import csv
import json
import math
import os
import subprocess
import sys
import tempfile
import traceback


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import fetch_genes as fg
from ground_truth import load_ground_truth


N_UNIVERSE = 36e6
ALPHA = 0.5
EPS = 1e-12
PLACEHOLDER_WEIGHTS = {
    "z_rel": 0.60,
    "spec_adj": 0.25,
    "logFE": 0.15,
}
REQUIRED_COLUMNS = (
    "symbol",
    "co_papers",
    "gene_papers",
    "specificity",
    "spec_adj",
    "z_rel",
    "breadth_random",
    "hub_penalty",
    "track",
)
RANKING_ORDER = (
    "co_papers",
    "specificity",
    "spec_adj",
    "spec_adj_artifact",
    "enrichment_z",
    "z_rel",
    "cdrs_rank_score",
)
METRIC_ORDER = ("P@10", "P@20", "nDCG@20", "AUPRC")


# ============================================================================
# Metrics
# ============================================================================
def precision_at_k(ranked, gold, k):
    if k <= 0 or not ranked:
        return 0.0
    return sum(1 for gene in ranked[:k] if gene in gold) / k


def ndcg_at_k(ranked, gold, k):
    if k <= 0 or not ranked or not gold:
        return 0.0
    dcg = 0.0
    for index, gene in enumerate(ranked[:k]):
        if gene in gold:
            dcg += 1.0 / math.log2(index + 2)
    ideal_hits = min(k, len(gold), len(ranked))
    ideal = sum(1.0 / math.log2(index + 2) for index in range(ideal_hits))
    return dcg / ideal if ideal else 0.0


def auprc(ranked, gold):
    """Average precision over candidates only.

    Gold genes outside genes_all_scored.tsv are not retrievable by any offline
    ranking over that candidate list. The denominator is therefore gold
    intersect candidates, so this measures ranking quality among retrievable
    candidates rather than penalizing discovery recall from the upstream scan.
    """
    retrievable_gold = {gene for gene in ranked if gene in gold}
    if not retrievable_gold:
        return 0.0

    hits = 0
    total_precision = 0.0
    for index, gene in enumerate(ranked):
        if gene in retrievable_gold:
            hits += 1
            total_precision += hits / (index + 1)
    return total_precision / len(retrievable_gold)


# ============================================================================
# CDRS formulas
# ============================================================================
def _safe_float(value, default=0.0):
    if value is None:
        return default
    text = str(value).strip()
    if text == "":
        return default
    try:
        return float(text)
    except ValueError:
        return default


def _safe_int(value, default=0):
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def _percentiles(values):
    """Return rank/(n-1) percentiles in [0, 1]; n<=1 degrades to 1.0."""
    n_values = len(values)
    if n_values == 0:
        return []
    if n_values == 1:
        return [1.0]

    order = sorted(range(n_values), key=lambda index: (values[index], index))
    percentiles = [0.0] * n_values
    for rank, index in enumerate(order):
        percentiles[index] = rank / (n_values - 1)
    return percentiles


def _enrichment_z(co_papers, gene_papers, disease_total, n_universe):
    if gene_papers <= 0 or disease_total <= 0 or n_universe <= 1:
        return 0.0
    p0 = disease_total / n_universe
    expected = gene_papers * p0
    variance = gene_papers * p0 * (1 - p0) * (n_universe - gene_papers) / (n_universe - 1)
    return (co_papers - expected) / math.sqrt(variance) if variance > 0 else 0.0


def _logfe(co_papers, gene_papers, disease_total, n_universe):
    if gene_papers < 0 or disease_total < 0 or n_universe <= 0:
        return 0.0
    specificity = (co_papers + ALPHA) / (gene_papers + 2 * ALPHA)
    background = (disease_total + ALPHA) / (n_universe + 2 * ALPHA)
    return math.log2(max(specificity, EPS) / max(background, EPS))


def _artifact_weight(row):
    symbol = row.get("symbol", "")
    track = row.get("track", "")
    if track == "artifact" or fg.ARTIFACT_RE.match(symbol):
        return 0.5
    return 1.0


def compute_rankings(rows, disease_total, n_universe=N_UNIVERSE):
    """Return ranking name -> ranked symbols, derived only from scored columns."""
    if not rows:
        return {
            "co_papers": [],
            "specificity": [],
            "spec_adj": [],
            "spec_adj_artifact": [],
            "enrichment_z": [],
            "z_rel": [],
            "cdrs_rank_score": [],
        }

    co_papers = [row["co_papers"] for row in rows]
    gene_papers = [row["gene_papers"] for row in rows]
    specificity = [row["specificity"] for row in rows]
    spec_adj = [row["spec_adj"] for row in rows]
    spec_adj_artifact = [
        _artifact_weight(row) * row["spec_adj"]
        for row in rows
    ]
    z_rel = [row["z_rel"] for row in rows]
    logfe = [
        _logfe(co_papers[index], gene_papers[index], disease_total, n_universe)
        for index in range(len(rows))
    ]
    enrichment_z = [
        _enrichment_z(co_papers[index], gene_papers[index], disease_total, n_universe)
        for index in range(len(rows))
    ]

    p_z_rel = _percentiles(z_rel)
    p_spec_adj = _percentiles(spec_adj)
    p_logfe = _percentiles(logfe)

    cdrs_rank_score = []
    for index, row in enumerate(rows):
        weighted_sum = (
            PLACEHOLDER_WEIGHTS["z_rel"] * p_z_rel[index]
            + PLACEHOLDER_WEIGHTS["spec_adj"] * p_spec_adj[index]
            + PLACEHOLDER_WEIGHTS["logFE"] * p_logfe[index]
        )
        cdrs_rank_score.append(
            _artifact_weight(row) * row["hub_penalty"] * weighted_sum
        )

    def order_by(values):
        order = sorted(
            range(len(rows)),
            key=lambda index: (values[index], rows[index]["symbol"]),
            reverse=True,
        )
        return [rows[index]["symbol"] for index in order]

    return {
        "co_papers": order_by(co_papers),
        "specificity": order_by(specificity),
        "spec_adj": order_by(spec_adj),
        "spec_adj_artifact": order_by(spec_adj_artifact),
        "enrichment_z": order_by(enrichment_z),
        "z_rel": order_by(z_rel),
        "cdrs_rank_score": order_by(cdrs_rank_score),
    }


# ============================================================================
# IO
# ============================================================================
def load_scored(path):
    warnings = []
    with open(path, encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        rows = []
        for row_index, raw_row in enumerate(reader, start=2):
            row = {key: (value or "") for key, value in raw_row.items()}
            missing = [key for key in REQUIRED_COLUMNS if key not in row]
            if missing:
                warnings.append(
                    f"line {row_index}: missing columns defaulted: {', '.join(missing)}"
                )
            row["symbol"] = row.get("symbol", "").strip()
            row["co_papers"] = _safe_int(row.get("co_papers"))
            row["gene_papers"] = _safe_int(row.get("gene_papers"))
            row["specificity"] = _safe_float(row.get("specificity"))
            row["spec_adj"] = _safe_float(row.get("spec_adj"))
            row["z_rel"] = _safe_float(row.get("z_rel"))
            row["breadth_random"] = _safe_float(row.get("breadth_random"))
            row["hub_penalty"] = _safe_float(row.get("hub_penalty"), default=1.0)
            row["track"] = row.get("track", "").strip()
            if row["symbol"]:
                rows.append(row)
            else:
                warnings.append(f"line {row_index}: skipped row with empty symbol")
    return rows, warnings


def ensure_scored(disease):
    out_path = os.path.join(ROOT, "output", fg.slug(disease["keyword"]), "genes.tsv")
    scored_path = out_path.replace("genes.tsv", "genes_all_scored.tsv")
    if os.path.exists(scored_path):
        with open(scored_path, encoding="utf-8") as handle:
            if "z_rel" in handle.readline().rstrip("\n").split("\t"):
                return scored_path

    command = [
        sys.executable,
        os.path.join(ROOT, "scripts", "fetch_genes.py"),
        "--keyword",
        disease["keyword"],
        "--entity",
        disease["entity"],
        "--organism",
        "human",
        "--max",
        str(disease["max"]),
        "--scan",
        str(disease["scan"]),
        "--rank",
        "cdrs",
        "--out",
        out_path,
    ]
    print(f"running fetch_genes --rank cdrs for '{disease['keyword']}'")
    subprocess.run(command, check=True)
    return scored_path


def disease_total_from_pubtator(disease):
    return fg._pubtator_count(fg.search_text(disease["keyword"], disease["entity"]))[0]


# ============================================================================
# Evaluation and report
# ============================================================================
def score_rankings(rankings, gold):
    return {
        name: {
            "P@10": precision_at_k(ranked, gold, 10),
            "P@20": precision_at_k(ranked, gold, 20),
            "nDCG@20": ndcg_at_k(ranked, gold, 20),
            "AUPRC": auprc(ranked, gold),
        }
        for name, ranked in rankings.items()
    }


def render_report(disease, rows, rankings, scores, gt, disease_total, warnings=None):
    warnings = warnings or []
    gold = gt["gold"]
    candidates = {row["symbol"] for row in rows}
    gold_in_candidates = sorted(gold & candidates)
    cdrs_top20 = rankings.get("cdrs_rank_score", [])[:20]
    artifact_leakage = [symbol for symbol in cdrs_top20 if fg.ARTIFACT_RE.match(symbol)]
    related_hubs = [
        row["symbol"] for row in rows if row.get("track") == "related_pleiotropic"
    ]
    il_positions = {
        gene: (
            rankings["cdrs_rank_score"].index(gene) + 1
            if gene in rankings.get("cdrs_rank_score", [])
            else None
        )
        for gene in ("IL4", "IL13")
    }

    lines = [
        f"# CDRS bench - {disease['keyword']} (pilot)",
        "",
        f"- OpenTargets: {disease['mondo_id']} ({gt.get('disease_name') or 'unknown'}), "
        f"{gt['n_targets']} targets",
        f"- gold: genetic_association >= {disease['genetic_threshold']} "
        f"({len(gold)} genes)",
        f"- known_drug secondary label: {len(gt['known_drug'])} genes",
        f"- candidates scored: {len(rows)}; gold intersect candidates: "
        f"{len(gold_in_candidates)}",
        f"- M_D={disease_total}, N={N_UNIVERSE:.0f}",
        f"- CDRS PLACEHOLDER_WEIGHTS={PLACEHOLDER_WEIGHTS}",
        "- AUPRC denominator: gold intersect candidates only; gold outside the "
        "candidate list is not retrievable by offline re-ranking.",
        "",
        "## Ranking vs genetic gold",
        "",
        "| ranking | P@10 | P@20 | nDCG@20 | AUPRC |",
        "|---------|------|------|---------|-------|",
    ]
    for name in RANKING_ORDER:
        label = name
        if name == "spec_adj":
            label += " (current)"
        if name == "cdrs_rank_score":
            label += " (placeholder weights)"
        metric = scores[name]
        lines.append(
            f"| {label} | {metric['P@10']:.3f} | {metric['P@20']:.3f} | "
            f"{metric['nDCG@20']:.3f} | {metric['AUPRC']:.3f} |"
        )

    lines.extend(
        [
            "",
            "## Diagnostics (CDRS ranking)",
            "",
            f"- artifact leakage in top-20: {artifact_leakage or 'none'}",
            f"- related_pleiotropic track: {related_hubs or 'none'}",
            f"- IL4/IL13 rank position: {il_positions}",
            f"- gold intersect candidates: {gold_in_candidates or 'none'}",
        ]
    )
    if warnings:
        lines.extend(["", "## Load warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)
    if gt.get("error"):
        lines.extend(["", "## Ground-truth warning", "", f"- {gt['error']}"])
    return "\n".join(lines)


def evaluate(disease, refresh_gt=False):
    scored_path = ensure_scored(disease)
    rows, warnings = load_scored(scored_path)
    disease_total = disease_total_from_pubtator(disease)
    gt = load_ground_truth(
        disease["mondo_id"],
        disease["genetic_threshold"],
        refresh=refresh_gt,
    )
    rankings = compute_rankings(rows, disease_total)
    scores = score_rankings(rankings, gt["gold"])
    report = render_report(disease, rows, rankings, scores, gt, disease_total, warnings)
    candidates = {row["symbol"] for row in rows}
    gold_in_candidates = gt["gold"] & candidates
    return {
        "disease": disease,
        "report": report,
        "scores": scores,
        "meta": {
            "keyword": disease["keyword"],
            "n_gold": len(gt["gold"]),
            "n_gold_in_candidates": len(gold_in_candidates),
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


def _fmt_metric(value):
    return "NA" if value is None else f"{value:.3f}"


def render_summary(evaluations, errors=None):
    errors = errors or []
    aggregate = aggregate_scores(evaluations)
    lines = [
        "# CDRS bench - cross-disease summary",
        "",
        "## Mean ranking metrics",
        "",
        "Averaged across diseases with at least one gold-in-candidates.",
        "",
        "| ranking | mean P@10 | mean P@20 | mean nDCG@20 | mean AUPRC |",
        "|---------|-----------|-----------|--------------|------------|",
    ]
    for ranking in RANKING_ORDER:
        metric = aggregate["means"][ranking]
        label = ranking
        if ranking == "spec_adj":
            label += " (current)"
        if ranking == "cdrs_rank_score":
            label += " (placeholder weights)"
        lines.append(
            f"| {label} | {_fmt_metric(metric['P@10'])} | "
            f"{_fmt_metric(metric['P@20'])} | "
            f"{_fmt_metric(metric['nDCG@20'])} | "
            f"{_fmt_metric(metric['AUPRC'])} |"
        )

    skipped = aggregate["skipped"]
    lines.extend(["", "## Skipped from mean", ""])
    if skipped:
        lines.extend(f"- {keyword}: no gold-in-candidates" for keyword in skipped)
    else:
        lines.append("- none")

    lines.extend(
        [
            "",
            "## Per-disease breakdown",
            "",
            "| disease | n gold | n gold-in-candidates | ranking | nDCG@20 | AUPRC |",
            "|---------|--------|----------------------|---------|---------|-------|",
        ]
    )
    for result in evaluations:
        meta = result["meta"]
        for ranking in RANKING_ORDER:
            metric = result["scores"][ranking]
            lines.append(
                f"| {meta['keyword']} | {meta['n_gold']} | "
                f"{meta['n_gold_in_candidates']} | {ranking} | "
                f"{metric['nDCG@20']:.3f} | {metric['AUPRC']:.3f} |"
            )

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
            f"Best mean nDCG@20: {best_ndcg}; best mean AUPRC: {best_auprc}."
        )
    else:
        lines.append("No disease had gold-in-candidates; no mean verdict available.")

    lines.extend(
        [
            "",
            "## Caveat",
            "",
            "- Tuning set only.",
            "- CDRS weights are PLACEHOLDER values and unvalidated.",
            "- This is not an adoption claim.",
            "- method_dev requires the held-out 8 diseases plus paired Wilcoxon "
            "before claiming CDRS is better.",
        ]
    )
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
    gold = {"A", "B", "C"}
    assert precision_at_k(["A", "X", "B", "Y"], gold, 2) == 0.5
    assert precision_at_k([], gold, 10) == 0.0
    assert abs(ndcg_at_k(["A", "B", "C"], gold, 3) - 1.0) < 1e-9
    assert ndcg_at_k(["X", "Y", "Z"], gold, 3) == 0.0
    assert abs(auprc(["A", "B", "C", "X"], gold) - 1.0) < 1e-9
    assert abs(auprc(["X", "A", "B", "C"], gold) - ((1 / 2 + 2 / 3 + 3 / 4) / 3)) < 1e-9
    assert auprc(["X", "Y"], gold) == 0.0
    assert _percentiles([]) == []
    assert _percentiles([10]) == [1.0]
    assert _percentiles([10, 20, 30]) == [0.0, 0.5, 1.0]
    assert compute_rankings([], 100)["cdrs_rank_score"] == []

    rows = [
        {
            "symbol": "A",
            "co_papers": 20,
            "gene_papers": 100,
            "specificity": 0.2,
            "spec_adj": 0.12,
            "z_rel": 3.0,
            "breadth_random": 0.0,
            "hub_penalty": 1.0,
            "track": "established",
        },
        {
            "symbol": "IGHE",
            "co_papers": 30,
            "gene_papers": 200,
            "specificity": 0.15,
            "spec_adj": 0.13,
            "z_rel": 4.0,
            "breadth_random": 0.0,
            "hub_penalty": 1.0,
            "track": "artifact",
        },
    ]
    rankings = compute_rankings(rows, 1000)
    assert set(rankings) == {
        "co_papers",
        "specificity",
        "spec_adj",
        "spec_adj_artifact",
        "enrichment_z",
        "z_rel",
        "cdrs_rank_score",
    }
    assert "spec_adj_artifact" in rankings
    assert rankings["spec_adj"].index("IGHE") < rankings["spec_adj"].index("A")
    assert rankings["spec_adj_artifact"].index("IGHE") > rankings["spec_adj_artifact"].index("A")

    def fake_scores(base):
        return {
            ranking: {
                "P@10": base + 0.10,
                "P@20": base + 0.20,
                "nDCG@20": base + 0.30,
                "AUPRC": base + 0.40,
            }
            for ranking in RANKING_ORDER
        }

    fake_evaluations = [
        {
            "disease": {"keyword": "fake one"},
            "report": "fake report one",
            "scores": fake_scores(0.0),
            "meta": {
                "keyword": "fake one",
                "n_gold": 3,
                "n_gold_in_candidates": 2,
            },
        },
        {
            "disease": {"keyword": "fake two"},
            "report": "fake report two",
            "scores": fake_scores(1.0),
            "meta": {
                "keyword": "fake two",
                "n_gold": 4,
                "n_gold_in_candidates": 1,
            },
        },
        {
            "disease": {"keyword": "degenerate"},
            "report": "fake report degenerate",
            "scores": fake_scores(100.0),
            "meta": {
                "keyword": "degenerate",
                "n_gold": 5,
                "n_gold_in_candidates": 0,
            },
        },
    ]
    aggregate = aggregate_scores(fake_evaluations)
    assert abs(aggregate["means"]["co_papers"]["P@10"] - 0.60) < 1e-9
    assert abs(aggregate["means"]["z_rel"]["nDCG@20"] - 0.80) < 1e-9
    assert aggregate["skipped"] == ["degenerate"]
    summary = render_summary(fake_evaluations)
    assert "Best mean nDCG@20" in summary
    assert "degenerate: no gold-in-candidates" in summary
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = os.path.join(temp_dir, "cdrs_bench_SUMMARY.md")
        with open(temp_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(summary + "\n")
        assert os.path.exists(temp_path)
        with open(temp_path, encoding="utf-8") as handle:
            assert "mean P@10" in handle.read()

    print("ok: metric, percentile, ranking, and aggregation self-checks pass")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh-gt", action="store_true", help="re-fetch OpenTargets gold")
    parser.add_argument("--selftest", action="store_true", help="run metric self-checks and exit")
    args = parser.parse_args()

    if args.selftest:
        _selftest()
        return

    with open(os.path.join(HERE, "bench_diseases.json"), encoding="utf-8") as handle:
        config = json.load(handle)

    out_dir = os.path.join(HERE, "output")
    os.makedirs(out_dir, exist_ok=True)
    evaluations = []
    errors = []
    for disease in config["diseases"]:
        try:
            result = evaluate(disease, refresh_gt=args.refresh_gt)
        except Exception as exc:
            print(
                f"ERROR: failed to evaluate '{disease['keyword']}': {exc}",
                file=sys.stderr,
            )
            traceback.print_exc()
            errors.append({"keyword": disease["keyword"], "error": str(exc)})
            continue

        report = result["report"]
        out_path = os.path.join(out_dir, f"cdrs_bench_{fg.slug(disease['keyword'])}.md")
        with open(out_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(report + "\n")
        print(f"\n{report}\n\n-> {out_path}")
        evaluations.append(result)

    summary = render_summary(evaluations, errors)
    summary_path = os.path.join(out_dir, "cdrs_bench_SUMMARY.md")
    with open(summary_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(summary + "\n")
    print(f"\n{summary}\n\n-> {summary_path}")


if __name__ == "__main__":
    main()
