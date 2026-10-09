import pytest
from qdrant_client import QdrantClient

from tests.conftest import EMBED_DIM, FakeEmbeddingModel
from db import qdrant_client as qc

emb = FakeEmbeddingModel()


def point(pid, text, project="p1", user="u1", chunk="c", file="f1"):
    return {"point_id": pid, "vector": emb._vec(text), "project_id": project, "user_id": user,
            "file_id": file, "chunk_id": chunk, "source": "a.pdf", "page": 1}


def test_uninitialised_client_raises(monkeypatch):
    monkeypatch.setattr(qc, "_client", None)
    with pytest.raises(RuntimeError, match="init_qdrant"):
        qc.get_qdrant_client()


def test_init_creates_collection_once(monkeypatch, test_settings):
    shared = QdrantClient(":memory:")
    monkeypatch.setattr(qc, "QdrantClient", lambda **kw: shared)
    qc.init_qdrant(vector_size=EMBED_DIM)
    assert test_settings.qdrant_collection_name in [c.name for c in shared.get_collections().collections]
    qc.init_qdrant(vector_size=EMBED_DIM)     # idempotent
    assert len(shared.get_collections().collections) == 1


def test_init_wraps_connection_errors(monkeypatch):
    def boom(**kw):
        raise ConnectionError("down")
    monkeypatch.setattr(qc, "QdrantClient", boom)
    with pytest.raises(RuntimeError, match="Failed to initialize Qdrant"):
        qc.init_qdrant()


def test_empty_upsert_and_delete_are_noops(qdrant):
    qc.upsert_chunk_vectors([])
    qc.delete_points([])
    assert qc.get_collection_stats()["points_count"] == 0


def test_search_is_scoped_to_project(qdrant):
    qc.upsert_chunk_vectors([
        point("00000000-0000-0000-0000-000000000001", "metformin diabetes", project="p1", chunk="c1"),
        point("00000000-0000-0000-0000-000000000002", "metformin diabetes", project="p2", chunk="c2"),
    ])
    hits = qc.search(emb._vec("metformin diabetes"), "p1", top_k=5, score_threshold=0.1)
    assert [cid for cid, _ in hits] == ["c1"]


def test_search_is_scoped_to_user(qdrant):
    qc.upsert_chunk_vectors([
        point("00000000-0000-0000-0000-000000000001", "insulin", user="u1", chunk="mine"),
        point("00000000-0000-0000-0000-000000000002", "insulin", user="u2", chunk="theirs"),
    ])
    hits = qc.search(emb._vec("insulin"), "p1", 5, 0.1, user_id="u1")
    assert [c for c, _ in hits] == ["mine"]


def test_search_orders_by_score_and_respects_top_k_and_threshold(qdrant):
    qc.upsert_chunk_vectors([
        point("00000000-0000-0000-0000-000000000001", "insulin pump therapy", chunk="best"),
        point("00000000-0000-0000-0000-000000000002", "insulin and many other unrelated words here today", chunk="mid"),
        point("00000000-0000-0000-0000-000000000003", "completely different topic about trains", chunk="none"),
    ])
    q = emb._vec("insulin pump therapy")
    hits = qc.search(q, "p1", top_k=5, score_threshold=0.05)
    scores = [s for _, s in hits]
    assert scores == sorted(scores, reverse=True) and hits[0][0] == "best"
    assert "none" not in [c for c, _ in hits]
    assert len(qc.search(q, "p1", top_k=1, score_threshold=0.0)) == 1
    assert qc.search(q, "p1", top_k=5, score_threshold=0.999)[0][0] == "best"   # exact match survives
    assert qc.search(emb._vec("zzz qqq"), "p1", 5, 0.5) == []


def test_points_without_chunk_id_are_ignored(qdrant):
    p = point("00000000-0000-0000-0000-000000000001", "aspirin")
    p["chunk_id"] = ""
    qc.upsert_chunk_vectors([p])
    assert qc.search(emb._vec("aspirin"), "p1", 5, 0.1) == []


def test_delete_points(qdrant):
    qc.upsert_chunk_vectors([point("00000000-0000-0000-0000-000000000001", "x y z", chunk="c")])
    qc.delete_points(["00000000-0000-0000-0000-000000000001"])
    assert qc.get_collection_stats()["points_count"] == 0


def test_delete_by_file_and_project(qdrant):
    qc.upsert_chunk_vectors([
        point("00000000-0000-0000-0000-000000000001", "a b", project="p1", file="f1", chunk="1"),
        point("00000000-0000-0000-0000-000000000002", "a b", project="p1", file="f2", chunk="2"),
        point("00000000-0000-0000-0000-000000000003", "a b", project="p2", file="f3", chunk="3"),
    ])
    qc.delete_by_file("f1")
    assert qc.get_collection_stats()["points_count"] == 2
    qc.delete_by_project("p1")
    assert qc.get_collection_stats()["points_count"] == 1


def test_stats_handles_errors(monkeypatch):
    monkeypatch.setattr(qc, "_client", None)
    assert "error" in qc.get_collection_stats()


def test_no_threshold_keeps_negative_scores(qdrant):
    """The RAG fallback passes None: a "summarize the file" query can score below 0."""
    import uuid
    qc.upsert_chunk_vectors([{"point_id": str(uuid.uuid4()), "vector": [1.0] + [0.0] * (EMBED_DIM - 1),
                              "project_id": "p1", "file_id": "f1", "chunk_id": "c1", "source": "a.pdf", "page": 1}])
    opposite = [-1.0] + [0.0] * (EMBED_DIM - 1)
    assert qc.search(opposite, "p1", top_k=3, score_threshold=0.0) == []
    assert [cid for cid, _ in qc.search(opposite, "p1", top_k=3, score_threshold=None)] == ["c1"]
