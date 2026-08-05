"""
Data access layer for the Smart Medical Assistant.

- mongo_client: projects, file metadata, and chunk text (source of truth)
- qdrant_client: embedding vectors, filtered/searched per project
"""

from db import mongo_client
from db import qdrant_client

__all__ = ["mongo_client", "qdrant_client"]
