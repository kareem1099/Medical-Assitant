"""
Local RAG search tool for querying uploaded medical documents.

Search flow:
1. Embed the query
2. Search Qdrant, scoped to the currently active project, for similar chunk vectors
3. Resolve the matching chunk ids back to their full text in MongoDB
4. Format results with source attribution (filename, page, relevance score)

The tool itself only receives `query` from the LLM (that's the LangChain
tool-calling contract) — the active project is tracked separately via a
context variable set by the UI/workflow before each request, so concurrent
users each get their own project scope.
"""

import logging
from contextvars import ContextVar
from typing import Optional

from langchain.tools import tool

from config.settings import settings
from db import mongo_client
from db import qdrant_client
from tools.embeddings import embed_query


logger = logging.getLogger(__name__)

# Tracks which project the *current* request belongs to. Set via
# set_current_project() right before invoking the LangGraph workflow.
_current_project_id: ContextVar[Optional[str]] = ContextVar("current_project_id", default=None)


def set_current_project(project_id: Optional[str]) -> None:
    """Set the active project for the current request/context."""
    _current_project_id.set(project_id)


def get_current_project() -> Optional[str]:
    """Get the active project for the current request/context, if any."""
    return _current_project_id.get()


@tool
def medical_rag_search(query: str) -> str:
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
        - Results are filtered by score threshold (default 0.5)
        - Returns at most `top_k` chunks sorted by relevance (descending)
        - Requires a project to be selected and PDF documents to be uploaded first
    """
    if not query or not query.strip():
        error_msg = "Empty query provided. Please provide a question about your uploaded documents."
        logger.warning("Empty RAG query received")
        return f"Error: {error_msg}"

    query = query.strip()

    project_id = get_current_project()
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
            top_k=settings.top_k,
            score_threshold=settings.score_threshold,
        )

        if not hits:
            return (
                f"No relevant information found in this project's uploaded documents for query: {query}\n"
                f"(No uploaded documents yet, or no results above relevance threshold of {settings.score_threshold})"
            )

        # Resolve chunk text from MongoDB, preserving Qdrant's relevance order
        chunk_ids = [chunk_id for chunk_id, _score in hits]
        chunks_by_id = mongo_client.get_chunks_by_ids(chunk_ids)

        formatted_results = ["=== Local Document Search Results ===\n"]
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
            chunk_entry += f"Content: {content[:500]}{'...' if len(content) > 500 else ''}\n"
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
