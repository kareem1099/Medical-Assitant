import math
import subprocess
import sys
import textwrap

import tools.embeddings as emb


def test_embed_texts_shape_and_normalisation():
    vecs = emb.embed_texts(["metformin", "insulin pump"])
    assert len(vecs) == 2 and all(len(v) == emb.get_embedding_dimension() for v in vecs)
    assert all(math.isclose(sum(x * x for x in v), 1.0, rel_tol=1e-6) for v in vecs)


def test_embed_query_returns_single_vector():
    assert isinstance(emb.embed_query("hello")[0], float)


def test_similar_texts_score_higher_than_unrelated():
    a, b, c = (emb.embed_query(t) for t in ["type 2 diabetes metformin", "metformin for type 2 diabetes", "airplane engine repair"])
    dot = lambda x, y: sum(i * j for i, j in zip(x, y))
    assert dot(a, b) > dot(a, c)


def test_model_is_loaded_lazily_and_cached(monkeypatch):
    calls = []

    class Fake:
        def __init__(self, name, device=None):
            calls.append((name, device))

        def get_sentence_embedding_dimension(self):
            return 3

    fake_module = type(sys)("sentence_transformers")
    fake_module.SentenceTransformer = Fake
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    monkeypatch.setattr(emb, "_model", None)
    assert emb.get_embedding_dimension() == 3
    emb.get_embedding_model()
    assert len(calls) == 1 and calls[0][1] == "cpu"


def test_importing_tools_does_not_require_torch_or_sentence_transformers():
    """`import tools` used to import sentence-transformers (and torch) eagerly."""
    code = textwrap.dedent("""
        import sys
        sys.modules['sentence_transformers'] = None   # makes any import of it fail
        import tools, tools.pdf_loader, tools.rag_tool
        print('ok')
    """)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=str(__import__("pathlib").Path(__file__).resolve().parents[2]))
    assert out.stdout.strip().endswith("ok"), out.stderr[-500:]
