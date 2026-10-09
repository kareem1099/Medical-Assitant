from src.controllers.BaseController import BaseController


class WorkspaceController(BaseController):
    """Create and list workspaces owned by the authenticated user."""

    def create(self, user_id: str, name: str, description: str = "") -> str:
        if not name or not name.strip():
            raise ValueError("Workspace name is required")
        return self.metadata.create_workspace(user_id, name, description)

    def list_for_user(self, user_id: str):
        return self.metadata.list_workspaces(user_id)
