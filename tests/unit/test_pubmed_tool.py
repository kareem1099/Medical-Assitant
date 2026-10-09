import io
from urllib.error import HTTPError, URLError

import pytest

from tools import pubmed_tool as pt

ESEARCH = """<?xml version="1.0" encoding="UTF-8" ?>
<!DOCTYPE eSearchResult PUBLIC "-//NLM//DTD esearch 20060628//EN" "https://eutils.ncbi.nlm.nih.gov/eutils/dtd/20060628/esearch.dtd">
<eSearchResult><Count>{n}</Count><RetMax>{n}</RetMax><RetStart>0</RetStart><IdList>{ids}</IdList></eSearchResult>"""

EFETCH = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE PubmedArticleSet PUBLIC "-//NLM//DTD PubMedArticle, 1st January 2025//EN" "https://dtd.nlm.nih.gov/ncbi/pubmed/out/pubmed_250101.dtd">
<PubmedArticleSet>
<PubmedArticle><MedlineCitation Status="MEDLINE" Owner="NLM"><PMID Version="1">111</PMID>
<Article PubModel="Print"><Journal><JournalIssue CitedMedium="Print"><PubDate><Year>2023</Year><Month>Sep</Month><Day>12</Day></PubDate></JournalIssue><Title>Diabetes Care</Title></Journal>
<ArticleTitle>Metformin in type 2 diabetes: a meta-analysis.</ArticleTitle>
<Abstract><AbstractText Label="BACKGROUND">Metformin is first line.</AbstractText><AbstractText Label="RESULTS">HbA1c fell by 1.1%.</AbstractText></Abstract>
</Article></MedlineCitation></PubmedArticle>
<PubmedArticle><MedlineCitation Status="MEDLINE" Owner="NLM"><PMID Version="1">222</PMID>
<Article PubModel="Print"><Journal><JournalIssue CitedMedium="Print"><PubDate><MedlineDate>2022 Jan-Feb</MedlineDate></PubDate></JournalIssue><Title>Lancet</Title></Journal>
<ArticleTitle>No abstract article.</ArticleTitle></Article></MedlineCitation></PubmedArticle>
</PubmedArticleSet>"""


@pytest.fixture(autouse=True)
def clean_cache():
    pt.clear_pubmed_cache()
    yield
    pt.clear_pubmed_cache()


@pytest.fixture
def entrez(monkeypatch):
    """Patch the two network calls; the XML is parsed by the real Bio.Entrez.read."""
    calls = {"esearch": [], "efetch": []}
    state = {"ids": ["111", "222"]}

    def esearch(**kw):
        calls["esearch"].append(kw)
        ids = state["ids"]
        return io.BytesIO(ESEARCH.format(n=len(ids), ids="".join(f"<Id>{i}</Id>" for i in ids)).encode())

    def efetch(**kw):
        calls["efetch"].append(kw)
        return io.BytesIO(EFETCH.encode())

    monkeypatch.setattr(pt.Entrez, "esearch", esearch)
    monkeypatch.setattr(pt.Entrez, "efetch", efetch)
    return type("E", (), {"calls": calls, "state": state})


def run(query="metformin diabetes", email="me@example.com"):
    return pt.search_pubmed.invoke({"query": query}, config={"configurable": {"ncbi_email": email}})


def test_email_is_required(entrez):
    assert "valid NCBI email" in run(email="")
    assert "valid NCBI email" in run(email="not-an-email")
    assert entrez.calls["esearch"] == []


def test_settings_email_is_used_as_fallback(entrez, monkeypatch):
    monkeypatch.setattr(pt.settings, "ncbi_email", "fallback@example.com")
    assert "PubMed Search Results" in run(email="")
    assert entrez.calls["esearch"][0]["email"] == "fallback@example.com"


def test_empty_query(entrez):
    assert run(query="   ").startswith("Error: Empty query")


def test_parses_structured_abstracts_and_metadata(entrez):
    out = run()
    assert "Title: Metformin in type 2 diabetes: a meta-analysis." in out
    assert "Journal: Diabetes Care" in out
    assert "PMID: 111" in out
    assert "2023-Sep-12" in out
    assert "Metformin is first line." in out and "HbA1c fell by 1.1%." in out


def test_handles_missing_abstract_and_medline_date(entrez):
    out = run()
    assert "No abstract available" in out
    assert "2022 Jan-Feb" in out


def test_request_parameters(entrez, monkeypatch):
    monkeypatch.setattr(pt.settings, "top_k", 3)
    run()
    es = entrez.calls["esearch"][0]
    assert es["db"] == "pubmed" and es["retmax"] == 3 and es["sort"] == "relevance"
    assert entrez.calls["efetch"][0]["id"] == ["111", "222"]


def test_long_queries_are_truncated_to_500_chars(entrez):
    run(query="x" * 900)
    assert len(entrez.calls["esearch"][0]["term"]) == 500


def test_results_are_cached(entrez):
    first = run()
    second = run()
    assert first == second
    assert len(entrez.calls["esearch"]) == 1
    assert pt.get_cache_stats()["cached_queries"] == 1
    pt.clear_pubmed_cache()
    run()
    assert len(entrez.calls["esearch"]) == 2


def test_no_results_message(entrez):
    entrez.state["ids"] = []
    assert "No PubMed papers found" in run(query="zzzzqqqq")
    assert entrez.calls["efetch"] == []


def test_errors_are_returned_as_text_and_not_cached(monkeypatch):
    def raise_(exc):
        def _f(**kw):
            raise exc
        return _f

    for exc, needle in [
        (HTTPError("u", 429, "Too Many Requests", {}, None), "HTTP error (code 429)"),
        (URLError("dns failure"), "Unable to reach PubMed"),
        (RuntimeError("bad xml"), "PubMed API error"),
        (ValueError("weird"), "Unexpected error"),
    ]:
        monkeypatch.setattr(pt.Entrez, "esearch", raise_(exc))
        out = run(query=f"q-{needle}")
        assert out.startswith("Error:") and needle in out
    assert pt.get_cache_stats()["cached_queries"] == 0


def test_cache_expires(entrez, monkeypatch):
    run()
    for entry in pt._pubmed_cache.values():
        entry["timestamp"] = entry["timestamp"].replace(year=2000)
    run()
    assert len(entrez.calls["esearch"]) == 2


def test_cache_is_bounded(entrez):
    for i in range(pt.MAX_CACHE_ENTRIES + 20):
        run(query=f"query number {i}")
    assert pt.get_cache_stats()["cached_queries"] <= pt.MAX_CACHE_ENTRIES


def test_long_abstracts_are_not_cut_to_500_chars(entrez, monkeypatch):
    long_abs = "word " * 250 + "FINALWORD"
    xml = EFETCH.replace("<AbstractText Label=\"BACKGROUND\">Metformin is first line.</AbstractText>",
                         f"<AbstractText Label=\"BACKGROUND\">{long_abs}</AbstractText>")
    monkeypatch.setattr(pt.Entrez, "efetch", lambda **kw: io.BytesIO(xml.encode()))
    assert "FINALWORD" in run()
