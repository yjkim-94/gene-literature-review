"""Self-check for the specificity ranking (DESIGN.md 설계 D/E).

The whole point of the floor + Wilson lower bound is that a tiny-n perfect
ratio must NOT outrank a slightly-lower ratio backed by many papers. If this
breaks, the gene list promotes understudied co-occurrence artifacts to the top.
Note: the lower bound ALONE is insufficient (3/3 -> ~0.44 > 140/400 -> ~0.31);
the relative floor is what actually demotes the artifact. Both are tested here.
Run: python scripts/test_fetch_genes.py
"""
import json as _json
import fetch_genes
from fetch_genes import wilson_lower, rank_and_floor, search_text, co_query, entity_candidates, slug


def _row(sym, co, total):
    return {"symbol": sym, "co_papers": co, "gene_papers": total,
            "spec_adj": round(wilson_lower(co, total), 4)}


def test_tiny_n_artifact_ranks_below_core_gene():
    # a 3/3 artifact must not sit above a real 140/400 core gene
    rows = [_row("ARTIFACT", 3, 3), _row("CORE", 140, 400),
            _row("MID", 60, 120), _row("NOISE", 4, 5)]
    ranked = rank_and_floor(rows, min_gene_papers=10)
    order = [r["symbol"] for r in ranked]
    assert order.index("CORE") < order.index("ARTIFACT"), order
    assert ranked[-1]["symbol"] in ("ARTIFACT", "NOISE"), order


def test_specific_but_less_studied_core_gene_stays_on_top():
    # regression: a percentile floor demoted FDX1 (1565 papers, spec 0.66) below
    # broadly-studied siblings. A less-studied but highly-specific gene must win.
    rows = [_row("FDX1", 1032, 1565), _row("DLD", 569, 3711),
            _row("ATP7B", 563, 3681)]
    ranked = rank_and_floor(rows, min_gene_papers=10)
    assert ranked[0]["symbol"] == "FDX1", [r["symbol"] for r in ranked]


def test_below_floor_genes_kept_not_deleted():
    rows = [_row("ARTIFACT", 3, 3), _row("CORE", 140, 400)]
    ranked = rank_and_floor(rows, min_gene_papers=10)
    assert len(ranked) == 2  # demoted, not dropped


def test_entity_query_quotes_both_tokens_freetext_fallback():
    # entity present -> both tokens quoted (unquoted colon 400s on PubTator)
    assert co_query("2312", "atopic dermatitis", "@DISEASE_MESH:D003876") == \
        '"@GENE_2312" AND "@DISEASE_MESH:D003876"'
    assert search_text("atopic dermatitis", "@DISEASE_MESH:D003876") == '"@DISEASE_MESH:D003876"'
    # no entity -> free-text fallback, unquoted (novel terms with no MeSH)
    assert co_query("2312", "cuproptosis", "") == "@GENE_2312 AND cuproptosis"
    assert search_text("cuproptosis", "") == "cuproptosis"


def test_entity_candidates_parse_and_novel_fallback():
    # real term -> tokens extracted verbatim; novel term -> empty (free-text fallback)
    fetch_genes._get = lambda u: _json.dumps([
        {"_id": "@DISEASE_Dermatitis_Atopic", "biotype": "disease", "db_id": "D003876", "name": "Dermatitis Atopic"},
        {"_id": "@DISEASE_Dermatitis_Atopic_1", "biotype": "disease", "db_id": "C566404", "name": "Dermatitis Atopic 1"},
    ])
    cands = entity_candidates("atopic dermatitis")
    assert cands[0]["token"] == "@DISEASE_Dermatitis_Atopic", cands
    assert cands[0]["biotype"] == "disease"
    fetch_genes._get = lambda u: "[]"
    assert entity_candidates("cuproptosis") == []
    # empty / malformed body must not crash -> treated as no candidates
    fetch_genes._get = lambda u: ""
    assert entity_candidates("weird") == []
    fetch_genes._get = lambda u: '{"unexpected": "shape"}'
    assert entity_candidates("weird") == []


def test_slug_never_empty_and_isolates_non_ascii():
    # ascii -> readable kebab
    assert slug("Atopic Dermatitis") == "atopic-dermatitis"
    # non-ascii / all-symbol strips to "" -> must fall back, never empty
    assert slug("아토피") != ""
    assert slug("!!!") != ""
    # distinct non-ascii keywords must not collide on the same run dir
    assert slug("아토피") != slug("천식")


def test_wilson_lower_bounds_and_degenerate():
    assert wilson_lower(0, 0) == 0.0
    assert 0.0 <= wilson_lower(1, 5) <= 1.0
    assert abs(wilson_lower(700, 1000) - 0.7) < 0.03  # large n ~ point estimate
    assert wilson_lower(5, 5) < 1.0  # perfect ratio, small n -> shrunk


if __name__ == "__main__":
    test_tiny_n_artifact_ranks_below_core_gene()
    test_specific_but_less_studied_core_gene_stays_on_top()
    test_below_floor_genes_kept_not_deleted()
    test_entity_query_quotes_both_tokens_freetext_fallback()
    test_entity_candidates_parse_and_novel_fallback()
    test_slug_never_empty_and_isolates_non_ascii()
    test_wilson_lower_bounds_and_degenerate()
    print("ok: floor + wilson_lower demote tiny-n artifacts, keep specific core genes on top")
