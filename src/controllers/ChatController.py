from typing import Any, Callable, Dict, Optional

from src.controllers.BaseController import BaseController

DEFAULT_TITLE = "New conversation"
MAX_TITLE_CHARS = 60


def make_title(message: str) -> str:
    """Short, single-line conversation title derived from the first question."""
    title = " ".join(message.split())
    if len(title) > MAX_TITLE_CHARS:
        title = title[: MAX_TITLE_CHARS - 1].rstrip() + "…"
    return title


class ChatController(BaseController):
    """Coordinate workflow execution and conversation persistence."""

    def __init__(self, metadata_provider, workflow: Optional[Callable] = None):
        super().__init__(metadata_provider)
        self.workflow = workflow

    def start_turn(self, user_id: str, session_id: str, message: str):
        """Validate a new question; returns (stored messages, history incl. the question).

        Raises ValueError for an empty message and PermissionError for a
        conversation the user does not own.
        """
        if not message or not message.strip():
            raise ValueError("Message cannot be empty")
        existing = self.metadata.get_messages(user_id, session_id)
        return existing, [*existing, {"role": "user", "content": message}]

    def record_turn(self, user_id: str, session_id: str, message: str, result: Dict[str, Any], existing) -> None:
        """Persist a *successful* turn - a failed request never leaves a dangling question."""
        sources = result.get("sources") or []
        citations = result.get("citations") or [s["label"] for s in sources]
        source_types = result.get("source_types") or [s["type"] for s in sources]
        self.metadata.append_message(user_id, session_id, "user", message)
        self.metadata.append_message(user_id, session_id, "assistant", result.get("answer", ""),
                                     citations, source_types, sources)
        if not existing:
            conversation = self.metadata.get_conversation(user_id, session_id) or {}
            if conversation.get("title", DEFAULT_TITLE) == DEFAULT_TITLE:
                self.metadata.rename_conversation(user_id, session_id, make_title(message))

    def send_message(
        self,
        user_id: str,
        session_id: str,
        message: str,
        project_id: str | None = None,
        ncbi_email: str = "",
    ) -> Dict[str, Any]:
        if not message or not message.strip():
            raise ValueError("Message cannot be empty")
        if self.workflow is None:
            raise RuntimeError("Chat workflow has not been configured")

        existing, history = self.start_turn(user_id, session_id, message)
        result = self.workflow(
            message=message,
            history=history,
            project_id=project_id,
            ncbi_email=ncbi_email,
            user_id=user_id,
        )
        self.record_turn(user_id, session_id, message, result, existing)
        return {"answer": result.get("answer", ""), "citations": result.get("citations", []),
                "source_types": result.get("source_types", [])}
