#!/usr/bin/env python3
"""Offline regression test for fetch_pubmed's XML parsing.

The abstract/title extraction silently returned "" for any record whose text
starts with inline markup (PMID 34106037, measured), feeding empty text to the
summary step. This guards the itertext() fix with a canned XML snippet that
reproduces that exact shape.
"""
import json
import os
import sys
import tempfile
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_pubmed
from fetch_pubmed import parse_pubmed_xml, require_confirmation, search_pmids_entity

# AbstractText and ArticleTitle both LEAD with a child element, so plain .text is
# None -- the failure mode. Structured multi-part abstract + a PMC id too.
XML = """<PubmedArticleSet><PubmedArticle>
  <MedlineCitation>
    <PMID>34106037</PMID>
    <Article>
      <Journal><Title>Expert review of clinical immunology</Title>
        <JournalIssue><PubDate><Year>2021</Year></PubDate></JournalIssue></Journal>
      <ArticleTitle>Role of <i>IL31</i> in atopic dermatitis</ArticleTitle>
      <Abstract>
        <AbstractText Label="Introduction"><b>Atopic dermatitis</b> (AD) is common.</AbstractText>
        <AbstractText Label="Areas covered">IL-31 drives <sub>2</sub> itch signaling.</AbstractText>
      </Abstract>
    </Article>
  </MedlineCitation>
  <PubmedData>
    <ArticleIdList>
      <ArticleId IdType="pubmed">34106037</ArticleId>
      <ArticleId IdType="pmc">PMC8000000</ArticleId>
    </ArticleIdList>
    <ReferenceList><Reference><ArticleIdList>
      <ArticleId IdType="pubmed">99999999</ArticleId>
      <ArticleId IdType="pmc">PMC9999999</ArticleId>
    </ArticleIdList></Reference></ReferenceList>
  </PubmedData>
</PubmedArticle></PubmedArticleSet>"""


def test_inline_markup_text_not_dropped():
    recs = parse_pubmed_xml(XML)
    assert len(recs) == 1, recs
    r = recs[0]
    assert r["pmid"] == "34106037"
    assert r["url"] == "https://pubmed.ncbi.nlm.nih.gov/34106037/"
    assert r["retracted"] is False
    # body text that lives AFTER the leading child must survive
    assert "Atopic dermatitis" in r["abstract"], r["abstract"]
    assert "itch signaling" in r["abstract"], r["abstract"]
    assert r["abstract"], "abstract must not be empty"
    assert "IL31" in r["title"], r["title"]
    # pmcid must be the ARTICLE's own (PMC8000000), never the ReferenceList decoy
    # (PMC9999999) that a descendant .//ArticleId scan would wrongly pick up.
    assert r["access"] == "full-text" and r["pmcid"] == "PMC8000000", r["pmcid"]


def test_empty_and_missing():
    assert parse_pubmed_xml("<PubmedArticleSet></PubmedArticleSet>") == []


def test_retracted_publication_flagged():
    xml = """<PubmedArticleSet><PubmedArticle>
      <MedlineCitation>
        <PMID>1</PMID>
        <Article>
          <ArticleTitle>Retracted paper</ArticleTitle>
          <PublicationTypeList>
            <PublicationType UI="D016441">Retracted Publication</PublicationType>
          </PublicationTypeList>
        </Article>
      </MedlineCitation>
    </PubmedArticle></PubmedArticleSet>"""
    recs = parse_pubmed_xml(xml)
    assert recs[0]["retracted"] is True


def test_retraction_notice_not_flagged():
    xml = """<PubmedArticleSet><PubmedArticle>
      <MedlineCitation>
        <PMID>2</PMID>
        <Article>
          <ArticleTitle>Retraction notice</ArticleTitle>
          <PublicationTypeList>
            <PublicationType UI="D016440">Retraction of Publication</PublicationType>
          </PublicationTypeList>
        </Article>
      </MedlineCitation>
    </PubmedArticle></PubmedArticleSet>"""
    recs = parse_pubmed_xml(xml)
    assert recs[0]["retracted"] is False


def _mock_pubtator(pages):
    """Fake _get that serves canned PubTator search pages keyed by &page=N and
    records every URL it was asked for (so the query form can be asserted)."""
    calls = []

    def fake_get(url):
        calls.append(url)
        page = int(urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["page"][0])
        return json.dumps(pages[page])

    return fake_get, calls


def _swap(fake_get):
    """Install fake_get (and a no-op sleep) on the module, return a restore fn."""
    orig_get, orig_sleep = fetch_pubmed._get, fetch_pubmed._sleep
    fetch_pubmed._get, fetch_pubmed._sleep = fake_get, lambda: None
    def restore():
        fetch_pubmed._get, fetch_pubmed._sleep = orig_get, orig_sleep
    return restore


def test_entity_search_scores_and_topn():
    # single page, out-of-order scores -> top-n by score desc, PMIDs as strings
    pages = {1: {"count": 4, "total_pages": 1, "results": [
        {"pmid": 111, "score": 0.2}, {"pmid": 222, "score": 0.9},
        {"pmid": 333, "score": 0.5}, {"pmid": 444, "score": 0.1},
    ]}}
    fake_get, calls = _mock_pubtator(pages)
    restore = _swap(fake_get)
    try:
        pmids = search_pmids_entity("2312", "@DISEASE_MESH:D003876", 3)
    finally:
        restore()
    assert pmids == ["222", "333", "111"], pmids
    # query is the entity form (quoted @GENE_<id>), page 1 requested
    assert "%22%40GENE_2312%22" in calls[0], calls[0]
    assert "page=1" in calls[0], calls[0]


def test_entity_search_pages_until_n():
    # n=5 spans two pages; must fetch page 2 then stop at total_pages
    pages = {
        1: {"total_pages": 2, "results": [
            {"pmid": 1, "score": 0.5}, {"pmid": 2, "score": 0.4}, {"pmid": 3, "score": 0.3}]},
        2: {"total_pages": 2, "results": [
            {"pmid": 4, "score": 0.9}, {"pmid": 5, "score": 0.8}, {"pmid": 6, "score": 0.7}]},
    }
    fake_get, calls = _mock_pubtator(pages)
    restore = _swap(fake_get)
    try:
        pmids = search_pmids_entity("847", "@DISEASE_MESH:D003876", 5)
    finally:
        restore()
    assert len(calls) == 2, calls  # paged once, then stopped at total_pages
    assert pmids == ["4", "5", "6", "1", "2"], pmids  # top 5 by score across pages


def test_entity_search_malformed_returns_empty():
    # a non-JSON body (e.g. an error page) must not crash -> empty, caller falls back
    restore = _swap(lambda url: "<html>not json</html>")
    try:
        assert search_pmids_entity("2312", "@X", 5) == []
    finally:
        restore()


def test_require_confirmation():
    with tempfile.TemporaryDirectory() as d:
        genes_path = os.path.join(d, "genes.tsv")
        with open(genes_path, "w", encoding="utf-8") as f:
            f.write("symbol\tname\nIL31\tinterleukin 31\n")
        try:
            require_confirmation(genes_path)
        except SystemExit:
            pass
        else:
            raise AssertionError("missing genes.confirmed must stop")

        with open(os.path.join(d, "genes.confirmed"), "w", encoding="utf-8") as f:
            f.write("OK\n")
        assert require_confirmation(genes_path) is None


if __name__ == "__main__":
    test_inline_markup_text_not_dropped()
    test_empty_and_missing()
    test_retracted_publication_flagged()
    test_retraction_notice_not_flagged()
    test_entity_search_scores_and_topn()
    test_entity_search_pages_until_n()
    test_entity_search_malformed_returns_empty()
    test_require_confirmation()
    print("ok: fetch_pubmed XML parsing, entity search, and confirmation gate")
