from src.services.citations import extract_sources, render_sources

PUBMED = """=== PubMed Search Results ===

Paper 1:
Title: Metformin in type 2 diabetes: a meta-analysis.
Journal: Diabetes Care
Date: 2023-Sep-12
PMID: 111
Abstract: x
--------------------------------------------------------------------------------

Paper 2:
Title: No abstract article.
Journal: Lancet
Date: 2022 Jan-Feb
PMID: 222
Abstract: No abstract available
"""

LOCAL = """=== Local Document Search Results ===

Chunk 1:
Source: guide.pdf
Page: 2
Relevance: 0.83
Content: abc
--------------------------------------------------------------------------------

Chunk 2:
Source: guide.pdf
Page: 2
Relevance: 0.51
Content: dup page

Chunk 3:
Source: guide.pdf
Page: 5
Relevance: 0.40
Content: other
"""


def outputs(**kw):
    return [{"tool": k, "content": v} for k, v in kw.items()]


def test_extract_pubmed_sources():
    srcs = extract_sources(outputs(search_pubmed=PUBMED))
    assert [s["type"] for s in srcs] == ["pubmed", "pubmed"]
    assert srcs[0]["pmid"] == "111" and srcs[0]["journal"] == "Diabetes Care"
    assert srcs[0]["url"] == "https://pubmed.ncbi.nlm.nih.gov/111/"


def test_extract_local_sources_dedupes_same_page_and_keeps_best_score():
    srcs = extract_sources(outputs(medical_rag_search=LOCAL))
    assert [(s["filename"], s["page"]) for s in srcs] == [("guide.pdf", 2), ("guide.pdf", 5)]
    assert srcs[0]["score"] == 0.83


def test_errors_and_empty_results_produce_no_sources():
    assert extract_sources(outputs(search_pubmed="Error: A valid NCBI email is required.")) == []
    assert extract_sources(outputs(medical_rag_search="No relevant information found in this project's uploaded documents")) == []
    assert extract_sources([]) == []


def test_render_groups_by_type_and_links_pubmed():
    srcs = extract_sources(outputs(search_pubmed=PUBMED, medical_rag_search=LOCAL))
    citations = [s["label"] for s in srcs]
    types = [s["type"] for s in srcs]
    md = render_sources(citations, types)
    assert "Sources" in md and "PubMed" in md and "Your documents" in md
    assert "https://pubmed.ncbi.nlm.nih.gov/111/" in md
    assert "guide.pdf" in md and "p. 2" in md


def test_render_empty_state_messages():
    assert "No sources" in render_sources([], [])
    assert "Start" in render_sources(None, None, empty="Start a conversation to see sources.")
