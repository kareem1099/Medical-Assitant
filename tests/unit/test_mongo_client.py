import pytest

from db import mongo_client as mc


def test_uninitialised_db_raises(monkeypatch):
    monkeypatch.setattr(mc, "_db", None)
    with pytest.raises(RuntimeError, match="init_mongo"):
        mc.get_db()


def test_project_crud(mongo_db):
    pid = mc.create_project("  CV review  ", " desc ", user_id="u1")
    project = mc.get_project(pid, user_id="u1")
    assert project["name"] == "CV review" and project["description"] == "desc"
    assert mc.get_project(pid, user_id="u2") is None          # ownership enforced
    assert mc.get_project(pid)["id"] == pid                   # no user filter -> visible


@pytest.mark.parametrize("name", ["", "   "])
def test_empty_project_name_rejected(mongo_db, name):
    with pytest.raises(ValueError):
        mc.create_project(name)


def test_list_projects_scoped_and_sorted(mongo_db):
    a = mc.create_project("a", user_id="u1")
    b = mc.create_project("b", user_id="u1")
    mc.create_project("c", user_id="u2")
    assert [p["id"] for p in mc.list_projects("u1")] == [b, a]
    assert len(mc.list_projects()) == 3


def test_get_project_with_malformed_id_returns_none_instead_of_crashing(mongo_db):
    assert mc.get_project("not-an-object-id", user_id="u1") is None


def test_file_status_transitions(mongo_db):
    fid = mc.create_file_record("p1", "a.pdf", 3)
    assert mc.list_files("p1")[0]["status"] == "processing"
    mc.mark_file_completed(fid, 7)
    f = mc.list_files("p1")[0]
    assert (f["status"], f["num_chunks"], f["num_pages"]) == ("completed", 7, 3)
    mc.mark_file_failed(fid, "boom")
    f = mc.list_files("p1")[0]
    assert (f["status"], f["error_message"]) == ("failed", "boom")
    assert mc.list_files("other-project") == []


def test_chunks_insert_and_fetch(mongo_db):
    ids = mc.insert_chunks([
        {"project_id": "p", "user_id": "u1", "file_id": "f", "source": "a.pdf", "page": 1,
         "chunk_index": 0, "text": "alpha", "qdrant_point_id": "q1"},
        {"project_id": "p", "user_id": "u2", "file_id": "f", "source": "a.pdf", "page": 2,
         "chunk_index": 1, "text": "beta", "qdrant_point_id": "q2"},
    ])
    assert len(ids) == 2
    assert mc.insert_chunks([]) == []
    assert mc.get_chunks_by_ids([]) == {}
    all_chunks = mc.get_chunks_by_ids(ids)
    assert {c["text"] for c in all_chunks.values()} == {"alpha", "beta"}
    only_u1 = mc.get_chunks_by_ids(ids, user_id="u1")
    assert [c["text"] for c in only_u1.values()] == ["alpha"]


def test_get_chunks_ignores_malformed_ids(mongo_db):
    assert mc.get_chunks_by_ids(["nonsense"]) == {}


def test_delete_chunks_by_file_returns_point_ids(mongo_db):
    mc.insert_chunks([
        {"project_id": "p", "file_id": "f1", "source": "a", "page": 1, "text": "x", "qdrant_point_id": "q1"},
        {"project_id": "p", "file_id": "f1", "source": "a", "page": 1, "text": "y", "qdrant_point_id": "q2"},
        {"project_id": "p", "file_id": "f2", "source": "b", "page": 1, "text": "z", "qdrant_point_id": "q3"},
    ])
    assert sorted(mc.delete_chunks_by_file("f1")) == ["q1", "q2"]
    assert mongo_db.chunks.count_documents({}) == 1


def test_delete_project_removes_files_and_chunks(mongo_db):
    pid = mc.create_project("p", user_id="u")
    mc.create_file_record(pid, "a.pdf", 1)
    mc.insert_chunks([{"project_id": pid, "file_id": "f", "source": "a", "page": 1, "text": "x", "qdrant_point_id": "q"}])
    mc.delete_project(pid)
    assert mc.get_project(pid) is None
    assert mongo_db.files.count_documents({}) == 0 and mongo_db.chunks.count_documents({}) == 0


def test_file_helpers(mongo_db):
    fid = mc.create_file_record("p", "a.pdf", 1)
    assert mc.get_file(fid)["filename"] == "a.pdf"
    assert mc.find_file_by_name("p", "a.pdf")["id"] == fid
    assert mc.find_file_by_name("p", "zzz.pdf") is None
    mc.delete_file(fid)
    assert mc.get_file(fid) is None
