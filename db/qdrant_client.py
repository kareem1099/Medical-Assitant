"""
Qdrant vector database layer for the Smart Medical Assistant.

Qdrant stores ONLY embedding vectors plus a small payload
(project_id, file_id, chunk_id, source, page) used for filtering and for
looking the full chunk text back up in MongoDB. The chunk text itself lives
in MongoDB (see db/mongo_client.py).

All chunks from every project live in a single Qdrant collection; queries
are scoped to a project using a payload filter on "project_id". This keeps
collection management simple while still giving each project an isolated
search space.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from config.settings import settings


logger = logging.getLogger(__name__)

_client: Optional[QdrantClient] = None

# sentence-transformers/all-MiniLM-L6-v2 -> 384 dims.
# If EMBEDDING_MODEL is changed, update this (or compute it dynamically at
# startup from the embedding model, see tools/embeddings.py).
DEFAULT_VECTOR_SIZE = 384


def init_qdrant(vector_size: int = DEFAULT_VECTOR_SIZE) -> QdrantClient:
    """
    Initialize the global Qdrant client and ensure the collection exists.

    Should be called once during application startup (see app.py).

    Args:
        vector_size: Dimensionality of the embedding vectors that will be stored.

    Returns:
        The QdrantClient instance.

    Raises:
        RuntimeError: If the connection to Qdrant cannot be established.
    """
    global _client

    try:
        logger.info(f"Connecting to Qdrant at {settings.qdrant_url}")
        _client = QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key or None,
        )

        collection_name = settings.qdrant_collection_name
        existing = [c.name for c in _client.get_collections().collections]

        if collection_name not in existing:
            logger.info(f"Creating Qdrant collection '{collection_name}' (size={vector_size})")
            _client.create_collection(
                collection_name=collection_name,
                vectors_config=qmodels.VectorParams(
                    size=vector_size,
                    distance=qmodels.Distance.COSINE,
                ),
            )
            # Index project_id so filtered search is fast
            _client.create_payload_index(
                collection_name=collection_name,
                field_name="project_id",
                field_schema=qmodels.PayloadSchemaType.KEYWORD,
            )
            _client.create_payload_index(
                collection_name=collection_name,
                field_name="file_id",
                field_schema=qmodels.PayloadSchemaType.KEYWORD,
            )
        else:
            logger.info(f"Qdrant collection '{collection_name}' already exists")

        logger.info("Qdrant initialized successfully")
        return _client

    except Exception as e:
        error_msg = f"Failed to initialize Qdrant at {settings.qdrant_url}: {str(e)}"
        logger.error(error_msg)
        raise RuntimeError(error_msg) from e


def get_qdrant_client() -> QdrantClient:
    """Return the initialized Qdrant client, raising if not yet initialized."""
    if _client is None:
        raise RuntimeError(
            "Qdrant has not been initialized. Call init_qdrant() during app startup."
        )
    return _client


def upsert_chunk_vectors(points: List[Dict[str, Any]]) -> None:
    """
    Upsert chunk vectors into Qdrant.

    Args:
        points: List of dicts, each with keys:
            - point_id (str, UUID4)
            - vector (List[float])
            - project_id (str)
            - file_id (str)
            - chunk_id (str)   # MongoDB chunk _id
            - source (str)     # original filename
            - page (int)
    """
    if not points:
        return

    qdrant_points = [
        qmodels.PointStruct(
            id=p["point_id"],
            vector=p["vector"],
            payload={
                "project_id": p["project_id"],
                "file_id": p["file_id"],
                "chunk_id": p["chunk_id"],
                "source": p["source"],
                "page": p["page"],
            },
        )
        for p in points
    ]

    get_qdrant_client().upsert(
        collection_name=settings.qdrant_collection_name,
        points=qdrant_points,
    )
    logger.info(f"Upserted {len(qdrant_points)} vectors into Qdrant")


def search(
    query_vector: List[float],
    project_id: str,
    top_k: int,
    score_threshold: float,
) -> List[Tuple[str, float]]:
    """
    Search for the most similar chunks within a single project.

    Args:
        query_vector: Embedding of the search query.
        project_id: Restrict the search to this project's chunks.
        top_k: Max number of results to return.
        score_threshold: Minimum cosine similarity score to include (0-1, higher = more similar).

    Returns:
        List of (chunk_id, score) tuples, sorted by score descending
        (Qdrant with COSINE distance already returns similarity, so higher is better).
    """
    results = get_qdrant_client().search(
        collection_name=settings.qdrant_collection_name,
        query_vector=query_vector,
        query_filter=qmodels.Filter(
            must=[
                qmodels.FieldCondition(
                    key="project_id",
                    match=qmodels.MatchValue(value=project_id),
                )
            ]
        ),
        limit=top_k,
        score_threshold=score_threshold,
    )

    return [(hit.payload["chunk_id"], hit.score) for hit in results]


def delete_points(point_ids: List[str]) -> None:
    """Delete vectors from Qdrant by point id (used when a file is removed)."""
    if not point_ids:
        return
    get_qdrant_client().delete(
        collection_name=settings.qdrant_collection_name,
        points_selector=qmodels.PointIdsList(points=point_ids),
    )
    logger.info(f"Deleted {len(point_ids)} vectors from Qdrant")


def get_collection_stats() -> Dict[str, Any]:
    """Return basic stats about the Qdrant collection."""
    try:
        info = get_qdrant_client().get_collection(settings.qdrant_collection_name)
        return {
            "collection": settings.qdrant_collection_name,
            "points_count": info.points_count,
            "vectors_count": info.vectors_count,
        }
    except Exception as e:
        logger.error(f"Error getting Qdrant collection stats: {e}")
        return {"error": str(e)}
