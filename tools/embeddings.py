"""
Embedding model wrapper for the Smart Medical Assistant.

Previously embeddings were generated implicitly by LangChain's Chroma
vectorstore wrapper. Since we now write vectors to Qdrant and text to
MongoDB ourselves, we load the sentence-transformers model directly.
"""

import logging
from typing import List, Optional

from sentence_transformers import SentenceTransformer

from config.settings import settings


logger = logging.getLogger(__name__)

_model: Optional[SentenceTransformer] = None


def get_embedding_model() -> SentenceTransformer:
    """Lazily load (and cache) the sentence-transformers embedding model."""
    global _model
    if _model is None:
        logger.info(f"Loading embedding model: {settings.embedding_model}")
        _model = SentenceTransformer(settings.embedding_model, device="cpu")
        logger.info(
            f"Embedding model loaded (dim={_model.get_sentence_embedding_dimension()})"
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
