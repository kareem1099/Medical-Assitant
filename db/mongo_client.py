"""
MongoDB data access layer for the Smart Medical Assistant.

MongoDB is the source of truth for:
- projects: user-created workspaces, each with its own isolated document set
- files: metadata about each uploaded PDF (per project)
- chunks: the actual extracted/split text of every document chunk (per project/file)

Qdrant only stores the embedding vectors + a small payload used to filter by
project and to look the chunk back up here in MongoDB.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

from config.settings import settings


logger = logging.getLogger(__name__)

# Global MongoDB client/database (initialized via init_mongo())
_client: Optional[MongoClient] = None
_db: Optional[Database] = None


def init_mongo() -> Database:
    """
    Initialize the global MongoDB client/database and required indexes.

    Should be called once during application startup (see app.py).

    Returns:
        The MongoDB Database instance.

    Raises:
        RuntimeError: If the connection to MongoDB cannot be established.
    """
    global _client, _db

    try:
        logger.info(f"Connecting to MongoDB at {settings.mongo_uri}")
        _client = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=5000)
        # Force a round trip so failures surface immediately at startup
        _client.admin.command("ping")

        _db = _client[settings.mongo_db_name]

        # Helpful indexes
        _db.projects.create_index("name")
        _db.files.create_index("project_id")
        _db.chunks.create_index("project_id")
        _db.chunks.create_index("file_id")
        _db.chunks.create_index("qdrant_point_id")

        logger.info(f"MongoDB connected. Database: {settings.mongo_db_name}")
        return _db

    except Exception as e:
        error_msg = f"Failed to connect to MongoDB at {settings.mongo_uri}: {str(e)}"
        logger.error(error_msg)
        raise RuntimeError(error_msg) from e


def get_db() -> Database:
    """Return the initialized MongoDB database, raising if not yet initialized."""
    if _db is None:
        raise RuntimeError(
            "MongoDB has not been initialized. Call init_mongo() during app startup."
        )
    return _db


def _projects() -> Collection:
    return get_db().projects


def _files() -> Collection:
    return get_db().files


def _chunks() -> Collection:
    return get_db().chunks


def _to_object_id(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except (InvalidId, TypeError) as e:
        raise ValueError(f"Invalid id: {value}") from e


# --------------------------------------------------------------------------
# Projects
# --------------------------------------------------------------------------

def create_project(name: str, description: str = "") -> str:
    """
    Create a new project (an isolated workspace of documents).

    Args:
        name: Human-friendly project name.
        description: Optional project description.

    Returns:
        The new project's id as a string.
    """
    name = name.strip()
    if not name:
        raise ValueError("Project name cannot be empty.")

    doc = {
        "name": name,
        "description": description.strip(),
        "created_at": datetime.utcnow(),
    }
    result = _projects().insert_one(doc)
    logger.info(f"Created project '{name}' ({result.inserted_id})")
    return str(result.inserted_id)


def list_projects() -> List[Dict[str, Any]]:
    """Return all projects sorted by creation date (newest first)."""
    projects = []
    for doc in _projects().find().sort("created_at", -1):
        projects.append({
            "id": str(doc["_id"]),
            "name": doc["name"],
            "description": doc.get("description", ""),
            "created_at": doc.get("created_at"),
        })
    return projects


def get_project(project_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a single project by id, or None if it doesn't exist."""
    doc = _projects().find_one({"_id": _to_object_id(project_id)})
    if not doc:
        return None
    return {
        "id": str(doc["_id"]),
        "name": doc["name"],
        "description": doc.get("description", ""),
        "created_at": doc.get("created_at"),
    }


def delete_project(project_id: str) -> None:
    """Delete a project along with all its files and chunks (Mongo side only)."""
    oid = _to_object_id(project_id)
    _chunks().delete_many({"project_id": project_id})
    _files().delete_many({"project_id": project_id})
    _projects().delete_one({"_id": oid})
    logger.info(f"Deleted project {project_id} (files + chunks removed from MongoDB)")


# --------------------------------------------------------------------------
# Files
# --------------------------------------------------------------------------

def create_file_record(project_id: str, filename: str, num_pages: int) -> str:
    """Create a 'processing' file record for a newly uploaded PDF."""
    doc = {
        "project_id": project_id,
        "filename": filename,
        "num_pages": num_pages,
        "num_chunks": 0,
        "status": "processing",
        "error_message": None,
        "uploaded_at": datetime.utcnow(),
    }
    result = _files().insert_one(doc)
    return str(result.inserted_id)


def mark_file_completed(file_id: str, num_chunks: int) -> None:
    _files().update_one(
        {"_id": _to_object_id(file_id)},
        {"$set": {"status": "completed", "num_chunks": num_chunks}}
    )


def mark_file_failed(file_id: str, error_message: str) -> None:
    _files().update_one(
        {"_id": _to_object_id(file_id)},
        {"$set": {"status": "failed", "error_message": error_message}}
    )


def list_files(project_id: str) -> List[Dict[str, Any]]:
    """List all files (and their processing status) belonging to a project."""
    files = []
    for doc in _files().find({"project_id": project_id}).sort("uploaded_at", -1):
        files.append({
            "id": str(doc["_id"]),
            "filename": doc["filename"],
            "num_pages": doc.get("num_pages", 0),
            "num_chunks": doc.get("num_chunks", 0),
            "status": doc.get("status", "unknown"),
            "error_message": doc.get("error_message"),
            "uploaded_at": doc.get("uploaded_at"),
        })
    return files


# --------------------------------------------------------------------------
# Chunks
# --------------------------------------------------------------------------

def insert_chunks(chunk_docs: List[Dict[str, Any]]) -> List[str]:
    """
    Bulk insert chunk documents.

    Each chunk_doc is expected to contain: project_id, file_id, source,
    page, chunk_index, text, qdrant_point_id.

    Returns:
        List of inserted MongoDB ids (as strings), in the same order as input.
    """
    if not chunk_docs:
        return []
    result = _chunks().insert_many(chunk_docs)
    return [str(_id) for _id in result.inserted_ids]


def get_chunks_by_ids(chunk_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    Fetch chunk documents by their MongoDB ids.

    Returns:
        Dict mapping chunk_id (str) -> chunk document.
    """
    if not chunk_ids:
        return {}
    object_ids = [_to_object_id(cid) for cid in chunk_ids]
    cursor = _chunks().find({"_id": {"$in": object_ids}})
    result = {}
    for doc in cursor:
        cid = str(doc["_id"])
        result[cid] = {
            "id": cid,
            "project_id": doc["project_id"],
            "file_id": doc["file_id"],
            "source": doc["source"],
            "page": doc["page"],
            "chunk_index": doc.get("chunk_index"),
            "text": doc["text"],
        }
    return result


def delete_chunks_by_file(file_id: str) -> List[str]:
    """
    Delete all chunks belonging to a file.

    Returns:
        The list of Qdrant point ids that referenced these chunks, so the
        caller can also remove them from Qdrant.
    """
    docs = list(_chunks().find({"file_id": file_id}, {"qdrant_point_id": 1}))
    point_ids = [d["qdrant_point_id"] for d in docs if d.get("qdrant_point_id")]
    _chunks().delete_many({"file_id": file_id})
    return point_ids
