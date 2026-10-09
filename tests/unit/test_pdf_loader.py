import PyPDF2
import pytest

from config.settings import settings
from db import mongo_client, qdrant_client
from tools import pdf_loader as pl


# ---------------------------------------------------------------- extraction
def test_extract_text_keeps_page_numbers(diabetes_pdf):
    pages = pl.extract_text_from_pdf(diabetes_pdf)
    assert [p["page"] for p in pages] == [1, 2, 3]
    assert "Metformin" in pages[0]["text"] and "Hypoglycemia" in pages[1]["text"]


def test_blank_pages_are_skipped_but_numbering_is_preserved(pdf_factory):
    path = pdf_factory("gap.pdf", ["first page text", "", "third page text"])
    pages = pl.extract_text_from_pdf(path)
    assert [p["page"] for p in pages] == [1, 3]
    assert pl._get_pdf_page_count(path) == 3


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        pl.extract_text_from_pdf(str(tmp_path / "nope.pdf"))


def test_corrupted_pdf_raises_read_error(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"this is definitely not a pdf")
    with pytest.raises(PyPDF2.errors.PdfReadError):
        pl.extract_text_from_pdf(str(bad))


def test_encrypted_pdf_is_rejected(tmp_path, diabetes_pdf):
    writer = PyPDF2.PdfWriter()
    for page in PyPDF2.PdfReader(diabetes_pdf).pages:
        writer.add_page(page)
    writer.encrypt("secret")
    enc = tmp_path / "enc.pdf"
    with open(enc, "wb") as fh:
        writer.write(fh)
    with pytest.raises(PyPDF2.errors.PdfReadError, match="encrypted"):
        pl.extract_text_from_pdf(str(enc))


# ------------------------------------------------------------------ chunking
def test_chunk_pages_empty():
    assert pl.chunk_pages([]) == []


def test_chunks_respect_size_and_keep_page_metadata():
    pages = [{"page": 1, "text": "alpha sentence. " * 60}, {"page": 2, "text": "beta sentence. " * 60}]
    chunks = pl.chunk_pages(pages)
    assert len(chunks) > 2
    assert all(len(c["text"]) <= settings.chunk_size for c in chunks)
    assert {c["page"] for c in chunks} == {1, 2}
    pages_in_order = [c["page"] for c in chunks]
    assert pages_in_order == sorted(pages_in_order)


def test_chunk_page_attribution_for_text_unique_to_page_two():
    pages = [{"page": 1, "text": "intro text about hospitals. " * 5},
             {"page": 2, "text": "UNIQUEMARKER discharge criteria"}]
    chunks = pl.chunk_pages(pages)
    marker = [c for c in chunks if "UNIQUEMARKER" in c["text"]]
    assert marker and marker[0]["page"] == 2


def test_identical_text_on_two_pages_is_attributed_to_the_right_page():
    """Repeated headers/footers are common in clinical PDFs; page 2 must not be reported as page 1."""
    same = "Standard hospital footer line repeated on every page. " * 5   # ~270 chars
    chunks = pl.chunk_pages([{"page": 1, "text": same}, {"page": 2, "text": same}])
    assert [c["page"] for c in chunks] == [1, 2]


# ------------------------------------------------------------- full pipeline
def test_process_pdf_happy_path(storage, diabetes_pdf):
    res = pl.process_pdf_for_project(diabetes_pdf, "proj-1", user_id="u1")
    assert res["success"] and res["num_chunks"] >= 3 and res["filename"] == "diabetes_protocol.pdf"

    f = mongo_client.list_files("proj-1")[0]
    assert (f["status"], f["num_pages"], f["num_chunks"]) == ("completed", 3, res["num_chunks"])
    assert storage["mongo"].chunks.count_documents({"project_id": "proj-1", "user_id": "u1"}) == res["num_chunks"]
    assert qdrant_client.get_collection_stats()["points_count"] == res["num_chunks"]

    # every Qdrant payload points back to a real Mongo chunk
    pts, _ = storage["qdrant"].scroll(settings.qdrant_collection_name, limit=100, with_payload=True)
    ids = [p.payload["chunk_id"] for p in pts]
    assert len(mongo_client.get_chunks_by_ids(ids)) == len(ids)


def test_blank_pdf_is_reported_and_leaves_no_trace(storage, pdf_factory):
    path = pdf_factory("blank.pdf", ["", ""])
    res = pl.process_pdf_for_project(path, "p", user_id="u")
    assert not res["success"] and "No text" in res["message"]
    assert mongo_client.list_files("p") == []
    assert qdrant_client.get_collection_stats()["points_count"] == 0


def test_corrupted_pdf_is_reported_not_raised(storage, tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"garbage")
    res = pl.process_pdf_for_project(str(bad), "p", user_id="u")
    assert not res["success"] and res["num_chunks"] == 0


def test_missing_file_is_reported_not_raised(storage, tmp_path):
    res = pl.process_pdf_for_project(str(tmp_path / "ghost.pdf"), "p", user_id="u")
    assert not res["success"] and "not found" in res["message"].lower()


def test_embedding_failure_marks_file_failed_and_cleans_up(storage, diabetes_pdf, monkeypatch):
    monkeypatch.setattr(pl, "embed_texts", lambda texts: (_ for _ in ()).throw(RuntimeError("model crashed")))
    res = pl.process_pdf_for_project(diabetes_pdf, "p", user_id="u")
    assert not res["success"] and "model crashed" in res["message"]
    assert mongo_client.list_files("p")[0]["status"] == "failed"
    # no half-ingested chunks may stay behind
    assert storage["mongo"].chunks.count_documents({}) == 0


def test_qdrant_failure_marks_file_failed_and_cleans_up(storage, diabetes_pdf, monkeypatch):
    monkeypatch.setattr(qdrant_client, "upsert_chunk_vectors", lambda pts: (_ for _ in ()).throw(ConnectionError("qdrant down")))
    res = pl.process_pdf_for_project(diabetes_pdf, "p", user_id="u")
    assert not res["success"]
    assert mongo_client.list_files("p")[0]["status"] == "failed"
    assert storage["mongo"].chunks.count_documents({}) == 0


def test_two_users_same_project_id_do_not_share_chunks(storage, diabetes_pdf):
    pl.process_pdf_for_project(diabetes_pdf, "p", user_id="alice")
    chunks = list(storage["mongo"].chunks.find({}))
    assert {c["user_id"] for c in chunks} == {"alice"}
