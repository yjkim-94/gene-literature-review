#!/usr/bin/env python3
# ============================================================================
# tune_weights.py
# ============================================================================
# Author:      yjkim
# Purpose:     Offline weight/config sweep for CDRS rank_score.
# Description: Re-ranks cached scored disease candidates across the CDRS
#              simplex grid and reports whether any config beats spec_adj on
#              mean nDCG@20 and mean AUPRC across the tuning set.
#              This script intentionally uses cached scored dumps and cached
#              ground truth only; it must not call PubTator or OpenTargets.
# ============================================================================
import json
import os
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_genes as fg
from cdrs_bench import (
    ALPHA,
    N_UNIVERSE,
    _artifact_weight,
    _logfe,
    _percentiles,
    auprc,
    load_scored,
    ndcg_at_k,
    precision_at_k,
)
from ground_truth import CACHE_DIR, load_ground_truth


DISEASE_TOTALS = {
    "atopic dermatitis": 64422,
    "asthma": 354789,
    "rheumatoid arthritis": 278193,
    "psoriasis": 106378,
}
REFERENCE_RANKINGS = ("spec_adj", "specificity", "z_rel")
METRICS = ("P@10", "P@20", "nDCG@20", "AUPRC")
OUTPUT_PATH = HERE / "output" / "weight_tuning.md"
NOTE_PATH = ROOT / "TUNE_NOTE.md"


# ============================================================================
# Grid and scoring
# ============================================================================
def simplex_grid(step=0.1):
    scale = int(round(1 / step))
    weights = []
    for z_units in range(scale + 1):
        for s_units in range(scale - z_units + 1):
            l_units = scale - z_units - s_units
            weights.append(
                (
                    z_units / scale,
                    s_units / scale,
                    l_units / scale,
                )
            )
    return weights


def selfcheck_grid():
    weights = simplex_grid()
    corners = {(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)}
    assert corners.issubset(set(weights))
    for weight in weights:
        assert all(value >= 0 for value in weight)
        assert abs(sum(weight) - 1.0) < 1e-9
    assert len(weights) == 66


def order_by(rows, values):
    order = sorted(
        range(len(rows)),
        key=lambda index: (values[index], rows[index]["symbol"]),
        reverse=True,
    )
    return [rows[index]["symbol"] for index in order]


def score_ranking(ranked, gold):
    return {
        "P@10": precision_at_k(ranked, gold, 10),
        "P@20": precision_at_k(ranked, gold, 20),
        "nDCG@20": ndcg_at_k(ranked, gold, 20),
        "AUPRC": auprc(ranked, gold),
    }


def mean_metrics(per_disease_metrics):
    return {
        metric: sum(item[metric] for item in per_disease_metrics) / len(per_disease_metrics)
        for metric in METRICS
    }


def cdrs_scores(prepared, weights, use_hub_penalty, use_artifact_weight):
    w_z, w_s, w_l = weights
    scores = []
    for index, row in enumerate(prepared["rows"]):
        base_score = (
            w_z * prepared["p_z_rel"][index]
            + w_s * prepared["p_spec_adj"][index]
            + w_l * prepared["p_logfe"][index]
        )
        multiplier = 1.0
        if use_hub_penalty:
            multiplier *= row["hub_penalty"]
        if use_artifact_weight:
            multiplier *= _artifact_weight(row)
        scores.append(multiplier * base_score)
    return scores


def evaluate_config(prepared_diseases, weights, use_hub_penalty, use_artifact_weight):
    per_disease = []
    for prepared in prepared_diseases:
        scores = cdrs_scores(
            prepared,
            weights,
            use_hub_penalty,
            use_artifact_weight,
        )
        ranked = order_by(prepared["rows"], scores)
        per_disease.append(score_ranking(ranked, prepared["gold"]))
    return mean_metrics(per_disease)


# ============================================================================
# Data loading
# ============================================================================
def require_cached_ground_truth(mondo_id):
    cache_path = Path(CACHE_DIR) / f"{mondo_id}.json"
    if not cache_path.exists():
        raise FileNotFoundError(
            f"missing cached ground truth: {cache_path}; refusing network fetch"
        )


def prepare_disease(disease):
    keyword = disease["keyword"]
    slug = disease.get("slug") or fg.slug(keyword)
    scored_path = ROOT / "output" / slug / "genes_all_scored.tsv"
    if not scored_path.exists():
        raise FileNotFoundError(f"missing scored dump: {scored_path}")
    if keyword not in DISEASE_TOTALS:
        raise KeyError(f"missing hardcoded disease_total for: {keyword}")

    require_cached_ground_truth(disease["mondo_id"])
    rows, warnings = load_scored(scored_path)
    gt = load_ground_truth(
        disease["mondo_id"],
        disease["genetic_threshold"],
        refresh=False,
    )
    gold = gt["gold"]
    candidates = {row["symbol"] for row in rows}
    gold_in_candidates = sorted(gold & candidates)

    logfe = [
        _logfe(
            row["co_papers"],
            row["gene_papers"],
            DISEASE_TOTALS[keyword],
            N_UNIVERSE,
        )
        for row in rows
    ]
    return {
        "keyword": keyword,
        "slug": slug,
        "rows": rows,
        "warnings": warnings,
        "gold": gold,
        "gold_in_candidates": gold_in_candidates,
        "p_z_rel": _percentiles([row["z_rel"] for row in rows]),
        "p_spec_adj": _percentiles([row["spec_adj"] for row in rows]),
        "p_logfe": _percentiles(logfe),
    }


def load_prepared_diseases():
    with open(HERE / "bench_diseases.json", encoding="utf-8") as handle:
        config = json.load(handle)
    diseases = [
        disease for disease in config["diseases"]
        if disease.get("split", "tuning") == "tuning"
    ]
    return [prepare_disease(disease) for disease in diseases]


def reference_metrics(prepared_diseases):
    results = {}
    for ranking in REFERENCE_RANKINGS:
        per_disease = []
        for prepared in prepared_diseases:
            ranked = order_by(
                prepared["rows"],
                [row[ranking] for row in prepared["rows"]],
            )
            per_disease.append(score_ranking(ranked, prepared["gold"]))
        results[ranking] = mean_metrics(per_disease)
    return results


def run_sweep(prepared_diseases):
    configs = []
    for weights in simplex_grid():
        for use_hub_penalty in (False, True):
            for use_artifact_weight in (False, True):
                metrics = evaluate_config(
                    prepared_diseases,
                    weights,
                    use_hub_penalty,
                    use_artifact_weight,
                )
                configs.append(
                    {
                        "weights": weights,
                        "use_hub_penalty": use_hub_penalty,
                        "use_artifact_weight": use_artifact_weight,
                        "metrics": metrics,
                    }
                )
    return configs


# ============================================================================
# Reporting
# ============================================================================
def fmt(value):
    return f"{value:.3f}"


def fmt_weights(weights):
    return f"w_z={weights[0]:.1f}, w_s={weights[1]:.1f}, w_l={weights[2]:.1f}"


def config_label(config):
    return (
        f"{fmt_weights(config['weights'])}; "
        f"hub_penalty={config['use_hub_penalty']}; "
        f"artifact_weight={config['use_artifact_weight']}"
    )


def render_toggle_table(prepared_diseases, weights):
    lines = [
        "| hub_penalty | artifact_weight | mean nDCG@20 | mean AUPRC |",
        "|-------------|-----------------|--------------|------------|",
    ]
    for use_hub_penalty in (False, True):
        for use_artifact_weight in (False, True):
            metrics = evaluate_config(
                prepared_diseases,
                weights,
                use_hub_penalty,
                use_artifact_weight,
            )
            lines.append(
                f"| {use_hub_penalty} | {use_artifact_weight} | "
                f"{fmt(metrics['nDCG@20'])} | {fmt(metrics['AUPRC'])} |"
            )
    return lines


def render_report(prepared_diseases, references, configs, best_both):
    spec_adj = references["spec_adj"]
    best_ndcg = max(
        configs,
        key=lambda item: (item["metrics"]["nDCG@20"], item["metrics"]["AUPRC"]),
    )
    best_auprc = max(
        configs,
        key=lambda item: (item["metrics"]["AUPRC"], item["metrics"]["nDCG@20"]),
    )
    toggle_weights = best_both["weights"] if best_both else best_ndcg["weights"]

    lines = [
        "# CDRS weight tuning",
        "",
        "Offline sweep over cached `genes_all_scored.tsv` dumps only.",
        "",
        "## Inputs",
        "",
        f"- diseases: {len(prepared_diseases)} tuning diseases",
        f"- simplex grid: {len(simplex_grid())} weight triplets x 4 toggle combos",
        f"- logFE constants: N_UNIVERSE={N_UNIVERSE:.0f}, ALPHA={ALPHA}",
        "- disease_total values are hardcoded PubTator counts; no PubTator calls.",
        "- OpenTargets ground truth is loaded only from existing `.gt_cache` files.",
        "",
        "| disease | candidates | gold-in-candidates |",
        "|---------|------------|--------------------|",
    ]
    for prepared in prepared_diseases:
        lines.append(
            f"| {prepared['keyword']} | {len(prepared['rows'])} | "
            f"{len(prepared['gold_in_candidates'])} "
            f"({', '.join(prepared['gold_in_candidates'])}) |"
        )

    lines.extend(
        [
            "",
            "## Reference rankings",
            "",
            "| ranking | mean nDCG@20 | mean AUPRC |",
            "|---------|--------------|------------|",
        ]
    )
    for ranking in ("spec_adj", "specificity", "z_rel"):
        metrics = references[ranking]
        label = f"{ranking} (current)" if ranking == "spec_adj" else ranking
        lines.append(
            f"| {label} | {fmt(metrics['nDCG@20'])} | "
            f"{fmt(metrics['AUPRC'])} |"
        )

    lines.extend(
        [
            "",
            "## Best configs",
            "",
            f"- Best by mean nDCG@20: {config_label(best_ndcg)}; "
            f"mean nDCG@20={fmt(best_ndcg['metrics']['nDCG@20'])}, "
            f"mean AUPRC={fmt(best_ndcg['metrics']['AUPRC'])}",
            f"- Best by mean AUPRC: {config_label(best_auprc)}; "
            f"mean nDCG@20={fmt(best_auprc['metrics']['nDCG@20'])}, "
            f"mean AUPRC={fmt(best_auprc['metrics']['AUPRC'])}",
            "",
            "## Verdict",
            "",
        ]
    )
    if best_both:
        lines.append(
            "YES: at least one CDRS config beats spec_adj on both mean nDCG@20 "
            f"and mean AUPRC. Best such config: {config_label(best_both)}; "
            f"mean nDCG@20={fmt(best_both['metrics']['nDCG@20'])}, "
            f"mean AUPRC={fmt(best_both['metrics']['AUPRC'])}."
        )
    else:
        lines.append(
            "NO: no swept CDRS config beats spec_adj on both mean nDCG@20 "
            "and mean AUPRC."
        )

    lines.extend(
        [
            "",
            "## Toggle effect",
            "",
            f"Holding weights at {fmt_weights(toggle_weights)}.",
            "",
            *render_toggle_table(prepared_diseases, toggle_weights),
            "",
            "## Caveat",
            "",
            "- Four diseases only.",
            "- Tiny gold-in-candidates counts (4/6/4/8) make means noisy.",
            "- A tuning-set win is not proof.",
            "- Held-out 8 diseases plus paired Wilcoxon are still required.",
            "- This only indicates whether CDRS is worth pursuing further.",
        ]
    )
    return "\n".join(lines)


def render_note(references, best_both, best_ndcg, best_auprc):
    spec_adj = references["spec_adj"]
    if best_both:
        verdict = (
            "YES - CDRS has a swept config that beats spec_adj on both metrics."
        )
        chosen = best_both
    else:
        verdict = (
            "NO - no swept CDRS config beats spec_adj on both metrics."
        )
        chosen = None

    lines = [
        "# TUNE NOTE",
        "",
        f"- verdict: {verdict}",
        f"- spec_adj: mean nDCG@20={fmt(spec_adj['nDCG@20'])}, "
        f"mean AUPRC={fmt(spec_adj['AUPRC'])}",
        f"- best nDCG config: {config_label(best_ndcg)}; "
        f"nDCG@20={fmt(best_ndcg['metrics']['nDCG@20'])}, "
        f"AUPRC={fmt(best_ndcg['metrics']['AUPRC'])}",
        f"- best AUPRC config: {config_label(best_auprc)}; "
        f"nDCG@20={fmt(best_auprc['metrics']['nDCG@20'])}, "
        f"AUPRC={fmt(best_auprc['metrics']['AUPRC'])}",
    ]
    if chosen:
        lines.append(
            f"- best dual-win config: {config_label(chosen)}; "
            f"nDCG@20={fmt(chosen['metrics']['nDCG@20'])}, "
            f"AUPRC={fmt(chosen['metrics']['AUPRC'])}"
        )
    return "\n".join(lines)


def main():
    selfcheck_grid()
    prepared_diseases = load_prepared_diseases()
    references = reference_metrics(prepared_diseases)
    configs = run_sweep(prepared_diseases)
    spec_adj = references["spec_adj"]
    winners = [
        config for config in configs
        if (
            config["metrics"]["nDCG@20"] > spec_adj["nDCG@20"]
            and config["metrics"]["AUPRC"] > spec_adj["AUPRC"]
        )
    ]
    best_both = None
    if winners:
        best_both = max(
            winners,
            key=lambda item: (item["metrics"]["nDCG@20"], item["metrics"]["AUPRC"]),
        )
    best_ndcg = max(
        configs,
        key=lambda item: (item["metrics"]["nDCG@20"], item["metrics"]["AUPRC"]),
    )
    best_auprc = max(
        configs,
        key=lambda item: (item["metrics"]["AUPRC"], item["metrics"]["nDCG@20"]),
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        render_report(prepared_diseases, references, configs, best_both) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    NOTE_PATH.write_text(
        render_note(references, best_both, best_ndcg, best_auprc) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    verdict = (
        "YES: a CDRS config beats spec_adj on both mean nDCG@20 and mean AUPRC"
        if best_both
        else "NO: no CDRS config beats spec_adj on both mean nDCG@20 and mean AUPRC"
    )
    print(verdict)
    print(f"spec_adj nDCG@20={fmt(spec_adj['nDCG@20'])}, AUPRC={fmt(spec_adj['AUPRC'])}")
    print(
        f"best nDCG: {config_label(best_ndcg)}; "
        f"nDCG@20={fmt(best_ndcg['metrics']['nDCG@20'])}, "
        f"AUPRC={fmt(best_ndcg['metrics']['AUPRC'])}"
    )
    print(
        f"best AUPRC: {config_label(best_auprc)}; "
        f"nDCG@20={fmt(best_auprc['metrics']['nDCG@20'])}, "
        f"AUPRC={fmt(best_auprc['metrics']['AUPRC'])}"
    )
    print(f"report: {OUTPUT_PATH}")
    print(f"note: {NOTE_PATH}")


if __name__ == "__main__":
    main()
