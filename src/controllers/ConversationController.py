from src.controllers.BaseController import BaseController


class ConversationController(BaseController):
    """Manage only conversations owned by the authenticated user."""

    def list_for_user(self, user_id: str, workspace_id: str | None = None):
        conversations = self.metadata.list_conversations(user_id)
        if workspace_id is None:
            return conversations
        return [item for item in conversations if item.get("workspace_id") == workspace_id]

    def create(self, user_id: str, workspace_id: str | None = None, title: str = "New conversation") -> str:
        return self.metadata.create_conversation(user_id, workspace_id, title)

    def messages(self, user_id: str, session_id: str):
        return self.metadata.get_messages(user_id, session_id)

    def rename(self, user_id: str, session_id: str, title: str) -> None:
        self.metadata.rename_conversation(user_id, session_id, title)

    def clear(self, user_id: str, session_id: str) -> None:
        self.metadata.clear_messages(user_id, session_id)

    def delete(self, user_id: str, session_id: str) -> None:
        self.metadata.delete_conversation(user_id, session_id)
