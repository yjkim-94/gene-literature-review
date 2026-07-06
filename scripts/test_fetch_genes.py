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
import threading
import time
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


def test_cdrs_cache_flushes_before_return_and_after_failure():
    rows = [
        {"symbol": "G1", "gene_id": "1", "co_papers": 5, "gene_papers": 20},
        {"symbol": "G2", "gene_id": "2", "co_papers": 5, "gene_papers": 20},
    ]
    panel_tokens = ["@DISEASE_A", "@DISEASE_B"]
    old_count = fetch_genes._pubtator_count
    old_workers = fetch_genes.MAX_WORKERS
    second_gene_started = threading.Event()
    release_second_gene = threading.Event()

    def fixed_count(query):
        if "@GENE_2" in query:
            second_gene_started.set()
            release_second_gene.wait(timeout=5)
        return 3, []

    with tempfile.TemporaryDirectory() as td:
        cache_path = os.path.join(td, "pubtator_counts.tsv")
        try:
            fetch_genes._pubtator_count = fixed_count
            fetch_genes.MAX_WORKERS = 2
            worker = threading.Thread(
                target=fetch_genes.cdrs_enrich,
                args=(rows, panel_tokens, {}),
                kwargs={"cache_path": cache_path},
            )
            worker.start()
            assert second_gene_started.wait(timeout=2)
            for _ in range(40):
                if os.path.exists(cache_path) and open(cache_path, encoding="utf-8").read():
                    break
                time.sleep(0.05)
            assert worker.is_alive()
            saved = open(cache_path, encoding="utf-8").read()
            assert "1\t@DISEASE_A\t3\n" in saved
            assert "1\t@DISEASE_B\t3\n" in saved
            release_second_gene.set()
            worker.join(timeout=2)
            assert not worker.is_alive()
        finally:
            fetch_genes._pubtator_count = old_count
            fetch_genes.MAX_WORKERS = old_workers

    rows = [
        {"symbol": "G1", "gene_id": "1", "co_papers": 5, "gene_papers": 20},
        {"symbol": "G2", "gene_id": "2", "co_papers": 5, "gene_papers": 20},
    ]

    def fail_on_second_gene(query):
        if "@GENE_2" in query:
            raise RuntimeError("simulated PubTator failure")
        return 4, []

    with tempfile.TemporaryDirectory() as td:
        cache_path = os.path.join(td, "pubtator_counts.tsv")
        cache = {}
        try:
            fetch_genes._pubtator_count = fail_on_second_gene
            fetch_genes.MAX_WORKERS = 2
            try:
                fetch_genes.cdrs_enrich(rows, panel_tokens, cache, cache_path)
            finally:
                fetch_genes.save_cache(cache, cache_path)
        except RuntimeError:
            pass
        finally:
            fetch_genes._pubtator_count = old_count
            fetch_genes.MAX_WORKERS = old_workers
        saved = open(cache_path, encoding="utf-8").read()
        assert "1\t@DISEASE_A\t4\n" in saved
        assert "1\t@DISEASE_B\t4\n" in saved


def test_spec_tsv_columns_unchanged_without_cdrs():
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
        header = open(path, encoding="utf-8").readline().rstrip("\n").split("\t")
    assert header == fetch_genes.TSV_COLS


if __name__ == "__main__":
    test_tiny_n_artifact_ranks_below_core_gene()
    test_specific_but_less_studied_core_gene_stays_on_top()
    test_below_floor_genes_kept_not_deleted()
    test_entity_query_quotes_both_tokens_freetext_fallback()
    test_entity_candidates_parse_and_novel_fallback()
    test_slug_never_empty_and_isolates_non_ascii()
    test_co_and_total_use_same_gene_form()
    test_wilson_lower_bounds_and_degenerate()
    test_cdrs_cache_flushes_before_return_and_after_failure()
    test_spec_tsv_columns_unchanged_without_cdrs()
    print("ok: floor + wilson_lower demote tiny-n artifacts, keep specific core genes on top")
