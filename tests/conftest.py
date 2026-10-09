"""
Shared fixtures for the whole test-suite.

Nothing here needs network access, Docker, GPU or real API keys:

* MongoDB   -> mongomock (in-memory, API compatible with pymongo)
* Qdrant    -> QdrantClient(":memory:") (the official local mode)
* Embedder  -> deterministic hashing bag-of-words model (no torch download)
* LLM       -> ScriptedChatModel (records prompts, returns scripted replies)
* PubMed    -> Bio.Entrez.esearch / efetch are patched with realistic XML
"""

from __future__ import annotations

import hashlib
import io
import math
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import mongomock
import pytest

# Make the project root importable no matter where pytest is launched from.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Never read the developer's real .env / keys during tests.
for _var in ("COHERE_API_KEY", "GEMINI_API_KEY", "NCBI_API_KEY", "QDRANT_API_KEY"):
    os.environ[_var] = ""

from qdrant_client import QdrantClient  # noqa: E402
from qdrant_client.http import models as qmodels  # noqa: E402

from config.settings import settings  # noqa: E402
from db import mongo_client, qdrant_client  # noqa: E402

EMBED_DIM = 256


# --------------------------------------------------------------------------
# Fake embedding model
# --------------------------------------------------------------------------
class FakeEmbeddingModel:
    """Hashing bag-of-words embedder: shared words => higher cosine score."""

    def get_sentence_embedding_dimension(self) -> int:
        return EMBED_DIM

    @staticmethod
    def _vec(text: str) -> List[float]:
        v = [0.0] * EMBED_DIM
        for tok in re.findall(r"[a-z0-9]+", text.lower()):
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            v[h % EMBED_DIM] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def encode(self, texts, normalize_embeddings=True, show_progress_bar=False):
        import numpy as np

        return np.array([self._vec(t) for t in texts])


@pytest.fixture(autouse=True)
def fake_embeddings(monkeypatch):
    import tools.embeddings as emb

    monkeypatch.setattr(emb, "_model", FakeEmbeddingModel())
    return emb


# --------------------------------------------------------------------------
# Settings: deterministic values for every test
# --------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def test_settings(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "llm_provider", "cohere")
    monkeypatch.setattr(settings, "cohere_api_key", "test-key")
    monkeypatch.setattr(settings, "gemini_api_key", "")
    monkeypatch.setattr(settings, "ncbi_email", "")
    monkeypatch.setattr(settings, "ncbi_api_key", "")
    monkeypatch.setattr(settings, "chunk_size", 400)
    monkeypatch.setattr(settings, "chunk_overlap", 50)
    monkeypatch.setattr(settings, "top_k", 5)
    monkeypatch.setattr(settings, "score_threshold", 0.15)
    monkeypatch.setattr(settings, "qdrant_collection_name", "test_chunks")
    monkeypatch.setattr(settings, "log_file", str(tmp_path / "app.log"))
    return settings


# --------------------------------------------------------------------------
# Storage backends
# --------------------------------------------------------------------------
@pytest.fixture
def mongo_db(monkeypatch):
    client = mongomock.MongoClient()
    db = client["medical_assistant_test"]
    monkeypatch.setattr(mongo_client, "_client", client)
    monkeypatch.setattr(mongo_client, "_db", db)
    return db


@pytest.fixture
def qdrant(monkeypatch, test_settings):
    client = QdrantClient(":memory:")
    client.create_collection(
        collection_name=test_settings.qdrant_collection_name,
        vectors_config=qmodels.VectorParams(size=EMBED_DIM, distance=qmodels.Distance.COSINE),
    )
    monkeypatch.setattr(qdrant_client, "_client", client)
    return client


@pytest.fixture
def storage(mongo_db, qdrant):
    """Both stores wired up (the usual starting point for integration tests)."""
    return {"mongo": mongo_db, "qdrant": qdrant}


@pytest.fixture
def metadata(mongo_db):
    from src.stores.metadata.MongoMetadataProvider import MongoMetadataProvider

    return MongoMetadataProvider(mongo_db)


# --------------------------------------------------------------------------
# Fake LLM
# --------------------------------------------------------------------------
class ScriptedChatModel:
    """
    Minimal stand-in for ChatCohere / ChatGoogleGenerativeAI.

    * bind_tools() returns self, so ``llm.bind_tools([...]).invoke(...)`` works.
    * Each invoke() pops the next scripted reply (or calls a callable).
    * Every prompt it receives is stored in ``.calls`` for assertions.
    """

    def __init__(self, replies: Optional[List[Any]] = None, default: str = "Scripted answer."):
        self.replies = list(replies or [])
        self.default = default
        self.calls: List[list] = []
        self.bound_tools: list = []

    def bind_tools(self, tools, **kwargs):
        self.bound_tools = list(tools)
        return self

    def invoke(self, messages, *args, **kwargs):
        from langchain_core.messages import AIMessage

        self.calls.append(list(messages))
        if not self.replies:
            return AIMessage(content=self.default)
        nxt = self.replies.pop(0)
        if callable(nxt):
            nxt = nxt(messages)
        if isinstance(nxt, Exception):
            raise nxt
        if isinstance(nxt, str):
            return AIMessage(content=nxt)
        return nxt


def tool_call_message(*calls):
    """Build an AIMessage that asks for tools: tool_call_message(("search_pubmed", {"query": "x"}))."""
    from langchain_core.messages import AIMessage

    return AIMessage(
        content="",
        tool_calls=[
            {"name": n, "args": a, "id": f"call_{i}", "type": "tool_call"}
            for i, (n, a) in enumerate(calls)
        ],
    )


@pytest.fixture
def fake_llm(monkeypatch):
    llm = ScriptedChatModel()
    import graph.nodes as nodes

    monkeypatch.setattr(nodes, "get_llm", lambda: llm)
    return llm


# --------------------------------------------------------------------------
# Sample PDFs (generated with reportlab so we test the real PyPDF2 path)
# --------------------------------------------------------------------------
def make_pdf(path: Path, pages: List[str]) -> str:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=A4)
    for text in pages:
        y = 800
        for line in text.split("\n"):
            c.drawString(50, y, line[:110])
            y -= 16
        c.showPage()
    c.save()
    return str(path)


@pytest.fixture
def pdf_factory(tmp_path):
    def _factory(name: str, pages: List[str]) -> str:
        return make_pdf(tmp_path / name, pages)

    return _factory


@pytest.fixture
def diabetes_pdf(pdf_factory):
    return pdf_factory(
        "diabetes_protocol.pdf",
        [
            "Hospital Diabetes Protocol\nMetformin is the first line medication for type 2 diabetes.\n"
            "Check HbA1c every three months for adult inpatients.",
            "Hypoglycemia management\nIf glucose is below 70 mg/dL give 15 grams of fast acting carbohydrate.\n"
            "Recheck blood glucose after fifteen minutes.",
            "Discharge criteria\nPatients may be discharged when glucose is stable and the education session is complete.",
        ],
    )
