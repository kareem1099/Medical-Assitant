"""Document management for workspaces: upload (with replace), delete, listing.

Kept free of any Gradio import so it can be unit-tested and reused by other
front-ends. Ownership of the workspace is always checked first.
"""

import logging
from typing import Any, Callable, Dict, List, Optional

from db import mongo_client, qdrant_client
from tools.pdf_loader import process_pdf_for_project

logger = logging.getLogger(__name__)


class WorkspaceAccessError(PermissionError):
    """The workspace does not exist or does not belong to the user."""


class DocumentService:
    def __init__(self, mongo=mongo_client, qdrant=qdrant_client, processor: Callable[..., Dict[str, Any]] = None):
        self.mongo = mongo
        self.qdrant = qdrant
        self.processor = processor or process_pdf_for_project

    # ------------------------------------------------------------------ helpers
    def _require_workspace(self, project_id: Optional[str], user_id: str) -> Dict[str, Any]:
        project = self.mongo.get_project(project_id, user_id=user_id) if project_id else None
        if not project:
            raise WorkspaceAccessError("Workspace not found. Select a workspace you own first.")
        return project

    def _remove_file(self, file_id: str) -> None:
        self.qdrant.delete_by_file(file_id)
        self.mongo.delete_chunks_by_file(file_id)
        self.mongo.delete_file(file_id)

    # --------------------------------------------------------------------- API
    def list_files(self, project_id: Optional[str], user_id: str) -> List[Dict[str, Any]]:
        if not project_id or not self.mongo.get_project(project_id, user_id=user_id):
            return []
        return self.mongo.list_files(project_id)

    def upload(self, pdf_path: str, project_id: Optional[str], user_id: str) -> Dict[str, Any]:
        """Ingest a PDF. Uploading a file with the same name *replaces* the old copy.

        The old copy is removed only after the new one was processed
        successfully, so a failed re-upload never destroys existing knowledge.
        """
        self._require_workspace(project_id, user_id)
        from pathlib import Path

        existing = self.mongo.find_file_by_name(project_id, Path(pdf_path).name)
        result = self.processor(pdf_path, project_id, user_id=user_id)
        result["replaced"] = False
        if result.get("success") and existing and existing["id"] != result.get("file_id"):
            try:
                self._remove_file(existing["id"])
                result["replaced"] = True
            except Exception as exc:  # the new copy is fine; just report it
                logger.warning(f"Could not remove the previous copy of {existing['filename']}: {exc}")
        return result

    def delete_file(self, file_id: str, project_id: Optional[str], user_id: str) -> str:
        self._require_workspace(project_id, user_id)
        record = self.mongo.get_file(file_id)
        if not record or record.get("project_id") != project_id:
            raise ValueError("File not found in this workspace.")
        self._remove_file(file_id)
        return record["filename"]

    def delete_workspace(self, project_id: Optional[str], user_id: str) -> str:
        project = self._require_workspace(project_id, user_id)
        self.qdrant.delete_by_project(project_id)
        self.mongo.delete_project(project_id)
        return project["name"]
