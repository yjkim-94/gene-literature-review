#!/usr/bin/env python3
# ============================================================================
# ground_truth.py
# ============================================================================
# Author:      yjkim
# Purpose:     OpenTargets genetic ground-truth loader for CDRS evaluation.
# Description: Loads literature-independent OpenTargets target scores for one
#              disease. Gold labels use genetic_association only; known_drug is
#              kept as a secondary label. Raw scores are cached under
#              evals/.gt_cache/ so thresholds can change without another fetch.
# ============================================================================
import json
import os
import urllib.error
import urllib.request


OT_API = "https://api.platform.opentargets.org/api/v4/graphql"
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".gt_cache")
PAGE_SIZE = 1000

QUERY = """
query AssociatedTargets($efoId: String!, $index: Int!, $size: Int!) {
  disease(efoId: $efoId) {
    name
    associatedTargets(
      page: {index: $index, size: $size}
      orderByScore: "score"
    ) {
      count
      rows {
        target {
          approvedSymbol
        }
        datatypeScores {
          id
          score
        }
      }
    }
  }
}
"""


def _empty_result(mondo_id, error=None):
    result = {
        "mondo_id": mondo_id,
        "disease_name": None,
        "n_targets": 0,
        "genetic": {},
        "known_drug": {},
        "clinical": {},
    }
    if error:
        result["error"] = error
    return result


def _post(query, variables):
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    request = urllib.request.Request(
        OT_API,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        data = json.loads(response.read().decode("utf-8"))
    if data.get("errors"):
        messages = "; ".join(str(err.get("message", err)) for err in data["errors"])
        raise RuntimeError(f"OpenTargets GraphQL error: {messages}")
    return data


def _fetch_all_rows(mondo_id, page_size=PAGE_SIZE):
    rows = []
    index = 0
    disease_name = None
    expected_count = None

    while True:
        data = _post(QUERY, {"efoId": mondo_id, "index": index, "size": page_size})
        disease = (data.get("data") or {}).get("disease")
        if not disease:
            return None, []

        disease_name = disease.get("name")
        associated = disease.get("associatedTargets") or {}
        page_rows = associated.get("rows") or []
        expected_count = associated.get("count", 0)
        rows.extend(page_rows)

        if not page_rows or len(rows) >= expected_count:
            break
        index += 1

    return disease_name, rows


def _build_raw(mondo_id):
    if not mondo_id:
        return _empty_result(mondo_id, error="empty mondo_id")

    try:
        disease_name, rows = _fetch_all_rows(mondo_id)
    except (RuntimeError, TimeoutError, urllib.error.URLError) as error:
        raw = _empty_result(mondo_id, error=f"OpenTargets fetch failed: {error}")
        raw["transient_error"] = True
        return raw
    if disease_name is None:
        return _empty_result(mondo_id, error="disease not found")

    raw = {
        "mondo_id": mondo_id,
        "disease_name": disease_name,
        "n_targets": len(rows),
        "genetic": {},
        "known_drug": {},
        "clinical": {},
    }
    for row in rows:
        symbol = ((row.get("target") or {}).get("approvedSymbol") or "").strip()
        if not symbol:
            continue
        for score in row.get("datatypeScores") or []:
            score_id = score.get("id")
            value = score.get("score") or 0.0
            if score_id == "genetic_association" and value > 0:
                raw["genetic"][symbol] = value
            elif score_id == "known_drug" and value > 0:
                raw["known_drug"][symbol] = value
            elif score_id == "clinical" and value > 0:
                raw["clinical"][symbol] = value
    return raw


def load_ground_truth(mondo_id, genetic_threshold, refresh=False):
    """Return gold and secondary labels for an OpenTargets disease id.

    The cache stores all positive genetic_association and known_drug scores.
    Applying genetic_threshold after loading the cache lets the benchmark change
    the gold cutoff without another network request.
    """
    cache_path = os.path.join(CACHE_DIR, f"{mondo_id or 'EMPTY'}.json")

    if os.path.exists(cache_path) and not refresh:
        with open(cache_path, encoding="utf-8") as handle:
            raw = json.load(handle)
    else:
        raw = _build_raw(mondo_id)
        if not raw.get("transient_error"):
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(cache_path, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(raw, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")

    genetic = raw.get("genetic") or {}
    known_drug = raw.get("known_drug") or {}
    clinical = raw.get("clinical") or {}
    gold = {symbol for symbol, score in genetic.items() if score >= genetic_threshold}
    return {
        "gold": gold,
        "known_drug": set(known_drug),
        "clinical": set(clinical),
        "genetic_all": genetic,
        "known_drug_all": known_drug,
        "clinical_all": clinical,
        "n_targets": raw.get("n_targets", 0),
        "disease_name": raw.get("disease_name"),
        "error": raw.get("error"),
    }


if __name__ == "__main__":
    gt = load_ground_truth("MONDO_0004980", 0.5)
    print(
        f"AD: {gt['n_targets']} OT targets, {len(gt['gold'])} genetic gold "
        f"(>=0.5), {len(gt['known_drug'])} known_drug"
    )
    if gt.get("error"):
        print(f"  error: {gt['error']}")
    missing = []
    for gene in ["FLG", "IL13"]:
        in_gold = gene in gt["gold"]
        print(f"  {gene}: genetic={gt['genetic_all'].get(gene)} in_gold={in_gold}")
        if not in_gold:
            missing.append(gene)
    if missing:
        raise SystemExit(f"smoke failed: missing AD genetic gold genes: {missing}")
