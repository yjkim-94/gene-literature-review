#!/usr/bin/env python3
# ============================================================================
# opentargets.py
# ============================================================================
# Author:      yjkim
# Purpose:     OpenTargets auxiliary target-score lookup for Phase 1 output.
# Description: Resolves a disease keyword to the top OpenTargets disease hit
#              and fetches genetic_association / clinical datatype scores.
#              This module is stdlib-only and has no ranking responsibility.
# ============================================================================
import json
import os
import urllib.error
import urllib.request


OT_API = "https://api.platform.opentargets.org/api/v4/graphql"
PAGE_SIZE = 1000

SEARCH_QUERY = """
query SearchDisease($q: String!) {
  search(
    queryString: $q
    entityNames: ["disease"]
    page: {index: 0, size: 1}
  ) {
    hits {
      id
      name
      entity
    }
  }
}
"""

TARGETS_QUERY = """
query AssociatedTargets($efoId: String!, $index: Int!, $size: Int!) {
  disease(efoId: $efoId) {
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


def resolve_efo(keyword):
    """Return (efo_id, disease_name) for the top disease hit, or None."""
    try:
        data = _post(SEARCH_QUERY, {"q": keyword})
    except (RuntimeError, TimeoutError, urllib.error.URLError, ValueError):
        return None

    hits = ((data.get("data") or {}).get("search") or {}).get("hits") or []
    if not hits:
        return None
    hit = hits[0]
    efo_id = hit.get("id")
    disease_name = hit.get("name")
    if not efo_id or not disease_name:
        return None
    return efo_id, disease_name


def fetch_target_scores(efo_id):
    """Return {approvedSymbol: {genetic: float, clinical: float}}."""
    scores = {}
    rows = []
    index = 0
    expected_count = None

    while True:
        data = _post(TARGETS_QUERY, {"efoId": efo_id, "index": index, "size": PAGE_SIZE})
        disease = (data.get("data") or {}).get("disease")
        if not disease:
            return {}

        associated = disease.get("associatedTargets") or {}
        page_rows = associated.get("rows") or []
        expected_count = associated.get("count", 0)
        rows.extend(page_rows)

        if not page_rows or len(rows) >= expected_count:
            break
        index += 1

    for row in rows:
        symbol = ((row.get("target") or {}).get("approvedSymbol") or "").strip()
        if not symbol:
            continue

        genetic = 0.0
        clinical = 0.0
        for datatype_score in row.get("datatypeScores") or []:
            score_id = datatype_score.get("id")
            value = datatype_score.get("score") or 0.0
            if score_id == "genetic_association":
                genetic = value
            elif score_id == "clinical":
                clinical = value

        if genetic > 0 or clinical > 0:
            scores[symbol] = {"genetic": genetic, "clinical": clinical}

    return scores


if __name__ == "__main__":
    if os.environ.get("OT_OFFLINE"):
        print("OpenTargets smoke skipped: OT_OFFLINE is set")
    else:
        resolved = resolve_efo("atopic dermatitis")
        print(f"resolve_efo('atopic dermatitis') -> {resolved}")
        if resolved:
            target_scores = fetch_target_scores(resolved[0])
            print(f"fetch_target_scores('{resolved[0]}') -> {len(target_scores)} targets")
