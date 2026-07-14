"""Self-check for the specificity ranking (DESIGN.md 설계 D/E).

The whole point of the floor + Wilson lower bound is that a tiny-n perfect
ratio must NOT outrank a slightly-lower ratio backed by many papers. If this
breaks, the gene list promotes understudied co-occurrence artifacts to the top.
Note: the lower bound ALONE is insufficient (3/3 -> ~0.44 > 140/400 -> ~0.31);
the relative floor is what actually demotes the artifact. Both are tested here.
Run: python scripts/test_fetch_genes.py
"""
import json as _json
import os
import tempfile
import fetch_genes
from fetch_genes import wilson_lower, rank_and_floor, search_text, co_query, gene_query, entity_candidates, slug


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


def test_artifact_weight_demotes_equal_spec_artifact_only():
    rows = [
        {"symbol": "IGHE", "co_papers": 50, "gene_papers": 100, "spec_adj": 0.5},
        {"symbol": "FLG", "co_papers": 50, "gene_papers": 100, "spec_adj": 0.5},
        {"symbol": "IL13", "co_papers": 80, "gene_papers": 100, "spec_adj": 0.8},
    ]
    ranked = rank_and_floor(rows, min_gene_papers=10)
    order = [r["symbol"] for r in ranked]
    assert order == ["IL13", "FLG", "IGHE"], order
    assert not fetch_genes.is_artifact("IL13")


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


def test_co_and_total_use_same_gene_form():
    # numerator and denominator must quote @GENE identically, else co can exceed
    # total and wilson_lower goes complex. Entity path: both quoted.
    assert gene_query("2312", "@DISEASE_X") == '"@GENE_2312"'
    assert co_query("2312", "kw", "@DISEASE_X").startswith('"@GENE_2312" AND ')
    # free-text path: both bare
    assert gene_query("2312", "") == "@GENE_2312"
    assert co_query("2312", "atopy", "").startswith("@GENE_2312 AND ")


def test_wilson_lower_bounds_and_degenerate():
    assert wilson_lower(0, 0) == 0.0
    assert 0.0 <= wilson_lower(1, 5) <= 1.0
    assert abs(wilson_lower(700, 1000) - 0.7) < 0.03  # large n ~ point estimate
    assert wilson_lower(5, 5) < 1.0  # perfect ratio, small n -> shrunk
    # k>n (transient count disagreement) must stay real, never complex -> no round() crash
    v = wilson_lower(5, 3)
    assert isinstance(v, float) and 0.0 <= v <= 1.0, v
    assert isinstance(round(v, 4), float)


def test_spec_tsv_columns_include_artifact_without_cdrs():
    rows = [_row("CORE", 140, 400)]
    rows[0].update({
        "gene_id": "1",
        "name": "core gene",
        "specificity": 0.35,
        "below_floor": False,
        "evidence_pmids": ["111", "222"],
    })
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "genes.tsv")
        fetch_genes.write_tsv(path, rows)
        lines = open(path, encoding="utf-8").read().splitlines()
        header = lines[0].split("\t")
        values = lines[1].split("\t")
    assert header == fetch_genes.TSV_COLS
    assert header[header.index("artifact")] == "artifact"
    assert values[header.index("artifact")] == "false"
    assert header[-2:] == ["ot_genetic", "ot_clinical"]
    assert values[-2:] == ["", ""]


def test_annotate_ot_rounds_matches_and_leaves_unmatched_empty():
    rows = [
        {"symbol": "FLG"},
        {"symbol": "IL13"},
        {"symbol": "NO_MATCH"},
    ]
    scores = {
        "FLG": {"genetic": 0.81234, "clinical": 0.45678},
        "IL13": {"genetic": 0.23456},
    }
    fetch_genes.annotate_ot(rows, scores)
    assert rows[0]["ot_genetic"] == 0.812
    assert rows[0]["ot_clinical"] == 0.457
    assert rows[1]["ot_genetic"] == 0.235
    assert rows[1]["ot_clinical"] == ""
    assert rows[2].get("ot_genetic", "") == ""
    assert rows[2].get("ot_clinical", "") == ""


def test_ot_candidates_keep_exact_human_symbol_only():
    calls = []

    def fake_exact(symbol, organism):
        calls.append((symbol, organism))
        if symbol == "IL7R":
            return "3575", {"name": "IL7R", "organism": {"scientificname": organism}}
        if symbol == "BAD":
            raise SystemExit("network failure: mock")
        return None

    old = fetch_genes.exact_symbol_gene
    old_sleep = fetch_genes.time.sleep
    fetch_genes.exact_symbol_gene = fake_exact
    fetch_genes.time.sleep = lambda _: None
    try:
        rows = fetch_genes.ot_candidates(
            {
                "NOPE": {"genetic": 0.1, "clinical": 0.0},
                "IL7R": {"genetic": 0.9, "clinical": 0.0},
                "BAD": {"genetic": 0.2, "clinical": 0.0},
            },
            "Homo sapiens",
        )
    finally:
        fetch_genes.exact_symbol_gene = old
        fetch_genes.time.sleep = old_sleep

    assert rows == [("3575", {"name": "IL7R", "organism": {"scientificname": "Homo sapiens"}})]
    assert calls[0] == ("BAD", "Homo sapiens")
    assert ("BAD", "Homo sapiens") in calls


def test_resolve_human_scores_ot_extra_then_cuts_by_filter():
    # An OT extra outside the scan pool IS scored, but is then subject to the
    # SAME min_co/min_spec filter as every other gene (option A: no bypass).
    cnt = {"1": 10}
    scan_rec = {"name": "SCAN", "description": "scan gene",
                "organism": {"scientificname": "Homo sapiens"}}
    ot_rec = {"name": "IL7R", "description": "interleukin 7 receptor",
              "organism": {"scientificname": "Homo sapiens"}}

    old_pick = fetch_genes.pick_candidates
    old_count = fetch_genes._pubtator_count
    fetch_genes.pick_candidates = lambda _cnt, _want, _pool: [("1", scan_rec)]

    def fake_count(query):
        if query in ('"@GENE_1"', '"@GENE_3575"'):
            return 100, []       # both have entity papers
        if query.startswith('"@GENE_1" AND '):
            return 20, ["111"]   # SCAN co-occurs -> passes min_co
        return 0, []             # IL7R co-query -> 0, below min_co

    fetch_genes._pubtator_count = fake_count
    try:
        genes, all_scored = fetch_genes.resolve_human(
            cnt,
            "atopic dermatitis",
            "@DISEASE_Dermatitis_Atopic",
            "human",
            5,
            0.0,
            1,
            10,
            [("3575", ot_rec)],
        )
    finally:
        fetch_genes.pick_candidates = old_pick
        fetch_genes._pubtator_count = old_count

    # scored despite not being in the scan cnt
    assert {row["symbol"] for row in all_scored} == {"SCAN", "IL7R"}
    # but cut by the normal filter (IL7R co=0 < min_co=1) -- not force-kept
    assert {row["symbol"] for row in genes} == {"SCAN"}
    il7r = next(row for row in all_scored if row["symbol"] == "IL7R")
    assert il7r["co_papers"] == 0
    assert il7r["gene_papers"] == 100


def test_ot_extra_zero_denominator_is_dropped():
    # An OT extra with no entity papers at all (total==0) is dropped like any
    # other zero-denominator candidate -- not kept as a zero-score row.
    ot_rec = {"name": "ZERO", "description": "zero denominator",
              "organism": {"scientificname": "Homo sapiens"}}

    old_pick = fetch_genes.pick_candidates
    old_count = fetch_genes._pubtator_count
    fetch_genes.pick_candidates = lambda _cnt, _want, _pool: []
    fetch_genes._pubtator_count = lambda _query: (0, [])
    try:
        genes, all_scored = fetch_genes.resolve_human(
            {},
            "atopic dermatitis",
            "@DISEASE_Dermatitis_Atopic",
            "human",
            1,
            0.0,
            1,
            10,
            [("999", ot_rec)],
        )
    finally:
        fetch_genes.pick_candidates = old_pick
        fetch_genes._pubtator_count = old_count

    assert genes == []
    assert all_scored == []


def test_ot_tie_order_uses_symbol_not_ot_score():
    old_exact = fetch_genes.exact_symbol_gene
    old_sleep = fetch_genes.time.sleep
    fetch_genes.exact_symbol_gene = lambda symbol, organism: (
        symbol,
        {"name": symbol, "organism": {"scientificname": organism}},
    )
    fetch_genes.time.sleep = lambda _: None
    try:
        rows = fetch_genes.ot_candidates(
            {
                "A_LOW": {"genetic": 0.1, "clinical": 0.0},
                "Z_HIGH": {"genetic": 0.9, "clinical": 0.0},
            },
            "Homo sapiens",
        )
    finally:
        fetch_genes.exact_symbol_gene = old_exact
        fetch_genes.time.sleep = old_sleep

    assert [gid for gid, _ in rows] == ["A_LOW", "Z_HIGH"]


def test_nongene_records_dropped_real_genes_kept():
    # Non-gene records (obsolete stub / QTL locus / PubTator collision) have
    # NO genomicinfo AND NO summary -- the exact shape esummary returned for
    # SEA(6395)/IGES(3478)/ST2(6761) on the atopic-dermatitis run.
    for name in ("S13 erythroblastosis (avian) oncogene homolog",
                 "immunoglobulin E concentration, serum",
                 "suppression of tumorigenicity 2"):
        rec = {"name": name, "genomicinfo": [], "summary": ""}
        assert fetch_genes.is_nongene_record(rec), name
    # Real genes have at least one of the two. ACTL9 scores low (geneweight
    # 476) yet is a real gene -- must be kept, so geneweight is not a criterion.
    real = [
        {"name": "FLG", "genomicinfo": [{"chrloc": "1"}], "summary": "filaggrin ..."},
        {"name": "ACTL9", "genomicinfo": [{"chrloc": "19"}], "summary": "Involved in ..."},
        # coordinates present but summary missing -> still a real gene (AND guard)
        {"name": "NEWGENE", "genomicinfo": [{"chrloc": "7"}], "summary": ""},
    ]
    for rec in real:
        assert not fetch_genes.is_nongene_record(rec), rec["name"]


if __name__ == "__main__":
    test_tiny_n_artifact_ranks_below_core_gene()
    test_specific_but_less_studied_core_gene_stays_on_top()
    test_below_floor_genes_kept_not_deleted()
    test_artifact_weight_demotes_equal_spec_artifact_only()
    test_entity_query_quotes_both_tokens_freetext_fallback()
    test_entity_candidates_parse_and_novel_fallback()
    test_slug_never_empty_and_isolates_non_ascii()
    test_co_and_total_use_same_gene_form()
    test_wilson_lower_bounds_and_degenerate()
    test_spec_tsv_columns_include_artifact_without_cdrs()
    test_annotate_ot_rounds_matches_and_leaves_unmatched_empty()
    test_ot_candidates_keep_exact_human_symbol_only()
    test_resolve_human_scores_ot_extra_then_cuts_by_filter()
    test_ot_extra_zero_denominator_is_dropped()
    test_ot_tie_order_uses_symbol_not_ot_score()
    test_nongene_records_dropped_real_genes_kept()
    print("ok: floor + wilson_lower demote tiny-n artifacts, keep specific core genes on top")
