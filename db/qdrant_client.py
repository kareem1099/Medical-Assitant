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
            timeout=settings.qdrant_timeout,
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
                "user_id": p.get("user_id"),
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
    score_threshold: Optional[float],
    user_id: Optional[str] = None,
) -> List[Tuple[str, float]]:
    """
    Search for the most similar chunks within a single project.

    Args:
        query_vector: Embedding of the search query.
        project_id: Restrict the search to this project's chunks.
        top_k: Max number of results to return.
        score_threshold: Minimum cosine similarity score to include (higher = more similar); None = no floor.

    Returns:
        List of (chunk_id, score) tuples, sorted by score descending
        (Qdrant with COSINE distance already returns similarity, so higher is better).
    """
    client = get_qdrant_client()
    conditions = [
            qmodels.FieldCondition(
                key="project_id",
                match=qmodels.MatchValue(value=project_id),
            )
    ]
    if user_id:
        conditions.append(qmodels.FieldCondition(key="user_id", match=qmodels.MatchValue(value=user_id)))
    query_filter = qmodels.Filter(must=conditions)

    # qdrant-client 1.10+ uses query_points; retain the legacy fallback for
    # deployments that still expose the former search method.
    if hasattr(client, "query_points"):
        response = client.query_points(
            collection_name=settings.qdrant_collection_name,
            query=query_vector,
            query_filter=query_filter,
            limit=top_k,
            score_threshold=score_threshold,
        )
        results = response.points
    else:
        results = client.search(
            collection_name=settings.qdrant_collection_name,
            query_vector=query_vector,
            query_filter=query_filter,
            limit=top_k,
            score_threshold=score_threshold,
        )

    return [
        (hit.payload["chunk_id"], hit.score)
        for hit in results
        if hit.payload and hit.payload.get("chunk_id")
    ]


def delete_points(point_ids: List[str]) -> None:
    """Delete vectors from Qdrant by point id (used when a file is removed)."""
    if not point_ids:
        return
    get_qdrant_client().delete(
        collection_name=settings.qdrant_collection_name,
        points_selector=qmodels.PointIdsList(points=point_ids),
    )
    logger.info(f"Deleted {len(point_ids)} vectors from Qdrant")


def _match_filter(key: str, value: str) -> "qmodels.Filter":
    return qmodels.Filter(must=[qmodels.FieldCondition(key=key, match=qmodels.MatchValue(value=value))])


def delete_by_file(file_id: str) -> None:
    """Delete every vector that belongs to one uploaded file."""
    get_qdrant_client().delete(
        collection_name=settings.qdrant_collection_name,
        points_selector=qmodels.FilterSelector(filter=_match_filter("file_id", file_id)),
    )
    logger.info(f"Deleted vectors of file {file_id} from Qdrant")


def delete_by_project(project_id: str) -> None:
    """Delete every vector that belongs to a project/workspace."""
    get_qdrant_client().delete(
        collection_name=settings.qdrant_collection_name,
        points_selector=qmodels.FilterSelector(filter=_match_filter("project_id", project_id)),
    )
    logger.info(f"Deleted vectors of project {project_id} from Qdrant")


def get_collection_stats() -> Dict[str, Any]:
    """Return basic stats about the Qdrant collection.

    ``vectors_count`` was removed from recent qdrant-client versions, so only
    ``points_count`` is relied upon (and reported under both names).
    """
    try:
        info = get_qdrant_client().get_collection(settings.qdrant_collection_name)
        points = getattr(info, "points_count", None) or 0
        return {
            "collection": settings.qdrant_collection_name,
            "points_count": points,
            "vectors_count": getattr(info, "vectors_count", None) or points,
        }
    except Exception as e:
        logger.error(f"Error getting Qdrant collection stats: {e}")
        return {"error": str(e)}
