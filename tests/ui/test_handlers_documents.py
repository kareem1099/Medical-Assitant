import shutil

import pytest

from db import mongo_client, qdrant_client
from tests.ui.conftest import val

# upload_pdf -> status, files_table, file_select, upload_box
# delete_file -> status, files_table, file_select


def chunks(storage, project):
    return storage["mongo"].chunks.count_documents({"project_id": project})


def test_upload_adds_document_and_clears_the_picker(signed_in, storage, diabetes_pdf):
    h, uid, project, _ = signed_in
    status, table, picker, box = h.upload_pdf(diabetes_pdf, project, uid)
    assert status.startswith("✅") and "diabetes_protocol.pdf" in status
    assert "diabetes_protocol.pdf" in table and box is None
    assert [n for n, _ in val(picker, "choices")] == ["diabetes_protocol.pdf"]
    assert chunks(storage, project) == qdrant_client.get_collection_stats()["points_count"] > 0


def test_uploading_the_same_file_again_replaces_instead_of_duplicating(signed_in, storage, diabetes_pdf):
    h, uid, project, _ = signed_in
    h.upload_pdf(diabetes_pdf, project, uid)
    n = chunks(storage, project)
    status, table, picker, _ = h.upload_pdf(diabetes_pdf, project, uid)
    assert "replaced" in status
    assert chunks(storage, project) == n and qdrant_client.get_collection_stats()["points_count"] == n
    assert len(val(picker, "choices")) == 1 and table.count("diabetes_protocol.pdf") == 1


def test_failed_reupload_keeps_the_old_copy(signed_in, storage, diabetes_pdf, tmp_path):
    h, uid, project, _ = signed_in
    h.upload_pdf(diabetes_pdf, project, uid)
    n = chunks(storage, project)
    broken = tmp_path / "diabetes_protocol.pdf"
    broken.write_bytes(b"not a pdf at all")
    status, *_ = h.upload_pdf(str(broken), project, uid)
    assert status.startswith("❌") and chunks(storage, project) == n


def test_same_name_in_two_workspaces_is_independent(signed_in, storage, diabetes_pdf):
    h, uid, p1, _ = signed_in
    p2 = h.create_workspace("Two", "", uid)[3]
    h.upload_pdf(diabetes_pdf, p1, uid)
    h.upload_pdf(diabetes_pdf, p2, uid)
    assert chunks(storage, p1) == chunks(storage, p2) > 0


@pytest.mark.parametrize("case,needle", [("no_user", "sign in"), ("no_project", "workspace"), ("no_file", "Choose")])
def test_upload_guards(signed_in, diabetes_pdf, case, needle):
    h, uid, project, _ = signed_in
    args = {"no_user": (diabetes_pdf, project, None), "no_project": (diabetes_pdf, None, uid),
            "no_file": (None, project, uid)}[case]
    assert needle.lower() in h.upload_pdf(*args)[0].lower()


def test_cannot_upload_into_someone_elses_workspace(signed_in, storage, diabetes_pdf):
    h, uid, project, _ = signed_in
    other = h.register("O", "o@x.co", "password-123")
    status = h.upload_pdf(diabetes_pdf, other[5], uid)[0]
    assert status.startswith("❌") and chunks(storage, other[5]) == 0


def test_unreadable_pdf_reports_reason(signed_in, tmp_path):
    h, uid, project, _ = signed_in
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"junk")
    status, table, *_ = h.upload_pdf(str(bad), project, uid)
    assert status.startswith("❌") and "bad.pdf" in status
    assert "No documents yet" in table                  # nothing half-registered is left behind


def test_unexpected_processor_crash_is_reported_not_raised(signed_in, diabetes_pdf, monkeypatch):
    h, uid, project, _ = signed_in
    monkeypatch.setattr(h.documents, "processor", lambda *a, **k: (_ for _ in ()).throw(MemoryError("secret path /x")))
    status = h.upload_pdf(diabetes_pdf, project, uid)[0]
    assert status.startswith("❌") and "/x" not in status


def test_delete_file_removes_chunks_and_vectors(signed_in, storage, diabetes_pdf):
    h, uid, project, _ = signed_in
    _, _, picker, _ = h.upload_pdf(diabetes_pdf, project, uid)
    file_id = val(picker, "choices")[0][1]
    status, table, picker = h.delete_file(file_id, project, uid)
    assert "Removed" in status and "No documents yet" in table and val(picker, "choices") == []
    assert chunks(storage, project) == 0 and qdrant_client.get_collection_stats()["points_count"] == 0


def test_delete_file_guards(signed_in, storage, diabetes_pdf):
    h, uid, project, _ = signed_in
    _, _, picker, _ = h.upload_pdf(diabetes_pdf, project, uid)
    file_id = val(picker, "choices")[0][1]
    assert "Pick" in h.delete_file(None, project, uid)[0]
    assert h.delete_file("64b64b64b64b64b64b64b64b", project, uid)[0].startswith("❌")
    other = h.register("O", "o@x.co", "password-123")
    assert h.delete_file(file_id, other[5], other[0])[0].startswith("❌")       # file of another workspace
    assert h.delete_file(file_id, project, other[0])[0].startswith("❌")        # not the owner
    assert chunks(storage, project) > 0
