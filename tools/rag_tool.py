"""
Local RAG search tool for querying uploaded medical documents.

Search flow:
1. Embed the query
2. Search Qdrant, scoped to the currently active project, for similar chunk vectors
3. Resolve the matching chunk ids back to their full text in MongoDB
4. Format results with source attribution (filename, page, relevance score)

The active project is passed via LangChain's RunnableConfig so that it
propagates correctly to tool threads spawned by LangGraph's ToolNode.
The workflow must be invoked with:
    config={"configurable": {"project_id": "<id>"}}
"""

import logging
import re
from typing import Optional

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig

from config.settings import settings
from db import mongo_client
from db import qdrant_client
from tools.embeddings import embed_query


logger = logging.getLogger(__name__)

FALLBACK_TOP_K = 3   # closest passages returned when the question names the file but nothing passes the threshold

_DOCUMENT_TERMS = {
    # English
    "uploaded", "upload", "source", "sources", "document", "documents", "file", "files",
    "pdf", "resume", "cv",
    # Arabic
    "الملف", "ملف", "الملفات", "مرفوع", "المرفوع", "مرفق", "المرفق", "المستند", "مستند",
    "الوثيقة", "وثيقة", "السيرة", "الذاتية",
}


def refers_to_uploaded_documents(query: Optional[str]) -> bool:
    """True when the question explicitly points at the user's own files."""
    return bool(set(re.findall(r"[\w']+", (query or "").lower())) & _DOCUMENT_TERMS)


@tool
def medical_rag_search(query: str, config: RunnableConfig) -> str:
    """
    Search uploaded medical documents (within the current project) using RAG.

    This tool searches the currently selected project's uploaded PDF
    documents using vector similarity search in Qdrant, then resolves the
    full chunk text from MongoDB. It returns the most relevant text chunks
    with source attribution including document name, page number, and
    relevance score.

    Args:
        query: Medical question to search in local documents.
               Should match terminology in uploaded documents.

    Returns:
        Formatted string containing:
        - Retrieved text content
        - Source document name
        - Page number
        - Relevance score (0.0-1.0, higher is better)

        Returns a helpful message if no project is selected or no documents
        are uploaded. Returns an error message if search fails.

    Notes:
        - Results are filtered by score threshold (default 0.2); questions that name the uploaded files fall back to the closest passages
        - Returns at most `top_k` chunks sorted by relevance (descending)
        - Requires a project to be selected and PDF documents to be uploaded first
    """
    if not query or not query.strip():
        error_msg = "Empty query provided. Please provide a question about your uploaded documents."
        logger.warning("Empty RAG query received")
        return f"Error: {error_msg}"

    query = query.strip()

    # Extract project_id from RunnableConfig (thread-safe, propagated by LangGraph)
    project_id = config.get("configurable", {}).get("project_id")
    user_id = config.get("configurable", {}).get("user_id")
    if not project_id:
        logger.warning("RAG tool called with no active project selected")
        return (
            "No project is currently selected. Please select or create a project "
            "and upload documents before asking questions about them."
        )

    logger.info(f"Searching local documents (project={project_id}) for: {query[:100]}...")

    try:
        query_vector = embed_query(query)

        hits = qdrant_client.search(
            query_vector=query_vector,
            project_id=project_id,
            user_id=user_id,
            top_k=settings.top_k,
            score_threshold=settings.score_threshold,
        )

        # "Summarize the file", Arabic questions or loosely worded ones score low
        # against the passages they are about. When the person explicitly asks
        # about their files, hand over the closest passages and let the model judge.
        low_relevance = False
        if not hits and refers_to_uploaded_documents(query):
            hits = qdrant_client.search(
                query_vector=query_vector,
                project_id=project_id,
                user_id=user_id,
                top_k=FALLBACK_TOP_K,
                score_threshold=None,   # no floor: cosine can be negative for "summarize the file"
            )
            low_relevance = bool(hits)

        if not hits:
            return (
                f"No relevant information found in this project's uploaded documents for query: {query}\n"
                f"(No uploaded documents yet, or no results above relevance threshold of {settings.score_threshold})"
            )

        # Resolve chunk text from MongoDB, preserving Qdrant's relevance order
        chunk_ids = [chunk_id for chunk_id, _score in hits]
        chunks_by_id = mongo_client.get_chunks_by_ids(chunk_ids, user_id=user_id)

        formatted_results = ["=== Local Document Search Results ===\n"]
        if low_relevance:
            formatted_results.append(
                "Note: no passage matched the question closely; these are the closest passages "
                "from the uploaded documents. Use them only if they actually answer the question.\n"
            )
        idx = 0
        for chunk_id, score in hits:
            chunk = chunks_by_id.get(chunk_id)
            if not chunk:
                logger.warning(f"Chunk {chunk_id} referenced by Qdrant but missing in MongoDB")
                continue

            idx += 1
            content = chunk["text"]
            chunk_entry = f"\nChunk {idx}:\n"
            chunk_entry += f"Source: {chunk['source']}\n"
            chunk_entry += f"Page: {chunk['page']}\n"
            chunk_entry += f"Relevance: {score:.2f}\n"
            chunk_entry += f"Content: {content}\n"
            chunk_entry += "-" * 80 + "\n"
            formatted_results.append(chunk_entry)

        if idx == 0:
            return f"No relevant information found in this project's uploaded documents for query: {query}"

        logger.info(f"Successfully retrieved {idx} relevant chunks")
        return "\n".join(formatted_results)

    except Exception as e:
        error_msg = f"Error searching local documents: {str(e)}"
        logger.error(f"RAG search error for query '{query[:50]}...': {e}", exc_info=True)
        return f"Error: {error_msg}"


def get_vectorstore_stats() -> dict:
    """Get statistics about the Qdrant collection (across all projects)."""
    return qdrant_client.get_collection_stats()
