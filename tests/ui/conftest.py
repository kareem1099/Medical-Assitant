import pytest

from ui.handlers import AppHandlers


class StubWorkflow:
    """Mimics the compiled LangGraph app: .invoke(state, config) -> state."""

    def __init__(self):
        self.calls = []
        self.answer = "Stub answer."
        self.tool_outputs = []
        self.error = None

    def invoke(self, state, config=None):
        self.calls.append({"state": state, "config": config})
        if self.error:
            raise self.error
        return {"final_answer": self.answer, "tool_outputs": self.tool_outputs}


@pytest.fixture
def workflow():
    return StubWorkflow()


@pytest.fixture
def h(storage, metadata, workflow):
    return AppHandlers(metadata, workflow)


def val(update, key="value"):
    """Read a field from a gr.update(...) dict."""
    return update.get(key) if isinstance(update, dict) else update


@pytest.fixture
def signed_in(h):
    """(handlers, user_id, project_id, session_id) for a freshly registered user."""
    out = h.register("Kareem", "kareem@example.com", "password-123")
    return h, out[0], out[5], out[8]   # user_id, project_id (ctx[0]), session_id (ctx[3])
