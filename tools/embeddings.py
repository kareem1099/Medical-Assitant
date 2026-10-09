"""
Embedding model wrapper for the Smart Medical Assistant.

Embeddings are generated here (sentence-transformers) and written to Qdrant by
the PDF loader; chunk text itself lives in MongoDB.

The heavy ``sentence_transformers`` / torch import happens lazily inside
:func:`get_embedding_model`, so importing ``tools`` (or running the unit
tests) does not pay that cost.
"""

import logging
from typing import TYPE_CHECKING, List, Optional

from config.settings import settings

if TYPE_CHECKING:  # pragma: no cover
    from sentence_transformers import SentenceTransformer


logger = logging.getLogger(__name__)

_model: Optional["SentenceTransformer"] = None


def get_embedding_model() -> "SentenceTransformer":
    """Lazily load (and cache) the sentence-transformers embedding model."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        logger.info("Loading embedding model: %s", settings.embedding_model)
        _model = SentenceTransformer(settings.embedding_model, device="cpu")
        logger.info(
            "Embedding model loaded (dim=%s)", _model.get_sentence_embedding_dimension()
        )
    return _model


def get_embedding_dimension() -> int:
    """Return the output vector size of the embedding model."""
    return get_embedding_model().get_sentence_embedding_dimension()


def embed_texts(texts: List[str]) -> List[List[float]]:
    """Embed a batch of texts, normalized for cosine similarity search."""
    model = get_embedding_model()
    embeddings = model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return embeddings.tolist()


def embed_query(text: str) -> List[float]:
    """Embed a single query string."""
    return embed_texts([text])[0]
