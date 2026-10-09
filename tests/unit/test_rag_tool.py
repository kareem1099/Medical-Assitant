import uuid

import pytest

from config.settings import settings
from db import mongo_client, qdrant_client
from tests.conftest import FakeEmbeddingModel
from tools.pdf_loader import process_pdf_for_project
from tools.rag_tool import medical_rag_search

emb = FakeEmbeddingModel()


def search(query, project="p1", user="u1"):
    return medical_rag_search.invoke(
        {"query": query}, config={"configurable": {"project_id": project, "user_id": user}}
    )


def test_empty_query():
    assert search("   ").startswith("Error: Empty query")


def test_no_project_selected():
    out = medical_rag_search.invoke({"query": "metformin"}, config={"configurable": {}})
    assert "No project is currently selected" in out


def test_nothing_uploaded_yet(storage):
    out = search("metformin first line")
    assert "No relevant information found" in out


def test_finds_the_right_page_and_reports_source(storage, diabetes_pdf):
    process_pdf_for_project(diabetes_pdf, "p1", user_id="u1")
    out = search("hypoglycemia glucose below 70 fast acting carbohydrate")
    assert "Source: diabetes_protocol.pdf" in out
    assert "Page: 2" in out
    assert "Relevance:" in out and "15 grams" in out


def test_results_are_isolated_per_project(storage, diabetes_pdf):
    process_pdf_for_project(diabetes_pdf, "p1", user_id="u1")
    assert "No relevant information" in search("metformin first line medication", project="p2")


def test_results_are_isolated_per_user(storage, diabetes_pdf):
    process_pdf_for_project(diabetes_pdf, "p1", user_id="u1")
    assert "No relevant information" in search("metformin first line medication", user="u2")


def test_threshold_filters_weak_matches(storage, diabetes_pdf, monkeypatch):
    process_pdf_for_project(diabetes_pdf, "p1", user_id="u1")
    monkeypatch.setattr(settings, "score_threshold", 0.95)
    assert "No relevant information" in search("metformin")


def test_top_k_limits_number_of_chunks(storage, diabetes_pdf, monkeypatch):
    process_pdf_for_project(diabetes_pdf, "p1", user_id="u1")
    monkeypatch.setattr(settings, "top_k", 1)
    monkeypatch.setattr(settings, "score_threshold", 0.0)
    assert search("diabetes glucose metformin discharge").count("Chunk ") == 1


def test_full_chunk_text_reaches_the_llm(storage, monkeypatch):
    """Chunks are up to CHUNK_SIZE chars; cutting them at 500 silently drops evidence."""
    text = "cardiology " * 40 + "ENDMARKER"     # ~450 chars -> use bigger below
    text = ("anticoagulation therapy " * 40) + "ENDMARKER"        # ~ 970 chars
    cid = mongo_client.insert_chunks([{"project_id": "p1", "user_id": "u1", "file_id": "f", "source": "a.pdf",
                                       "page": 1, "chunk_index": 0, "text": text, "qdrant_point_id": str(uuid.uuid4())}])[0]
    qdrant_client.upsert_chunk_vectors([{
        "point_id": str(uuid.uuid4()), "vector": emb._vec("anticoagulation therapy"), "project_id": "p1",
        "user_id": "u1", "file_id": "f", "chunk_id": cid, "source": "a.pdf", "page": 1}])
    assert "ENDMARKER" in search("anticoagulation therapy")


def test_orphan_vectors_without_mongo_chunk_are_skipped(storage):
    qdrant_client.upsert_chunk_vectors([{
        "point_id": str(uuid.uuid4()), "vector": emb._vec("orphan vector text"), "project_id": "p1",
        "user_id": "u1", "file_id": "f", "chunk_id": "64b64b64b64b64b64b64b64b", "source": "a", "page": 1}])
    assert "No relevant information" in search("orphan vector text")


def test_backend_errors_are_returned_as_text_not_raised(storage, monkeypatch):
    monkeypatch.setattr(qdrant_client, "search", lambda **kw: (_ for _ in ()).throw(ConnectionError("qdrant down")))
    out = search("anything here")
    assert out.startswith("Error:") and "qdrant down" in out


def test_question_about_the_file_falls_back_to_closest_passages(storage, diabetes_pdf, monkeypatch):
    """'Summarize the file' / Arabic questions score below the threshold against the file itself."""
    process_pdf_for_project(diabetes_pdf, "p1", user_id="u1")
    monkeypatch.setattr(settings, "score_threshold", 0.95)
    for query in ("Summarize the document I uploaded", "لخص الملف المرفوع"):
        out = search(query)
        assert "Source: diabetes_protocol.pdf" in out and "closest passages" in out, query
        assert out.count("Chunk ") <= 3


def test_fallback_never_crosses_projects_or_users(storage, diabetes_pdf, monkeypatch):
    process_pdf_for_project(diabetes_pdf, "p1", user_id="u1")
    monkeypatch.setattr(settings, "score_threshold", 0.95)
    assert "No relevant information" in search("summarize the uploaded file", project="p2")
    assert "No relevant information" in search("summarize the uploaded file", user="u2")
