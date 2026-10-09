from typing import Any


class GradioView:
    """Presentation-layer boundary for the future authenticated Gradio UI."""

    def __init__(self, auth_controller: Any, conversation_controller: Any, chat_controller: Any):
        self.auth_controller = auth_controller
        self.conversation_controller = conversation_controller
        self.chat_controller = chat_controller

    def build(self):
        """Build the authenticated UI in the next migration stage."""
        raise NotImplementedError("Authenticated Gradio view migration is the next stage")
