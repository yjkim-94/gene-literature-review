#!/usr/bin/env python3
"""Offline regression test for fetch_pubmed's XML parsing.

The abstract/title extraction silently returned "" for any record whose text
starts with inline markup (PMID 34106037, measured), feeding empty text to the
summary step. This guards the itertext() fix with a canned XML snippet that
reproduces that exact shape.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_pubmed import parse_pubmed_xml, require_confirmation

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
    test_require_confirmation()
    print("ok: fetch_pubmed XML parsing and confirmation gate")
