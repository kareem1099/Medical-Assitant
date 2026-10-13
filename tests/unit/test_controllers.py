import pytest

from src.controllers import AuthController, ChatController, ConversationController, WorkspaceController
from src.controllers.AuthController import VERIFY, EmailNotVerified


@pytest.fixture
def auth(metadata):
    return AuthController(metadata)


# ------------------------------------------------------------------- auth
def test_register_and_login(auth, metadata):
    uid = auth.register("Kareem@Example.com", "password-123", "Kareem")
    with pytest.raises(EmailNotVerified):
        auth.login("kareem@example.com", "password-123")
    _, code = auth.issue_code("kareem@example.com", VERIFY)
    auth.verify_email("kareem@example.com", code)
    user = auth.login("kareem@example.com", "password-123")
    assert user == {"id": uid, "email": "kareem@example.com", "display_name": "Kareem"}
    assert "password_hash" not in user


@pytest.mark.parametrize("email,name,msg", [("", "A", "email"), ("nope", "A", "email"), ("a@b.co", "  ", "Display name")])
def test_register_validation(auth, email, name, msg):
    with pytest.raises(ValueError, match=msg):
        auth.register(email, "password-123", name)


def test_register_short_password(auth):
    with pytest.raises(ValueError, match="8 characters"):
        auth.register("a@b.co", "short", "A")


def test_register_duplicate_email_any_case(auth, metadata):
    uid = auth.register("a@b.co", "password-123", "A")
    metadata.mark_email_verified(uid)
    with pytest.raises(ValueError, match="already exists"):
        auth.register("A@B.CO", "password-123", "A2")


@pytest.mark.parametrize("email,password", [("a@b.co", "wrong-password"), ("ghost@b.co", "password-123")])
def test_login_failures_share_one_message(auth, email, password):
    auth.register("a@b.co", "password-123", "A")
    with pytest.raises(PermissionError, match="Invalid email or password"):
        auth.login(email, password)


def test_login_updates_last_login(auth, metadata):
    metadata.mark_email_verified(auth.register("a@b.co", "password-123", "A"))
    assert metadata.find_user_by_email("a@b.co")["last_login_at"] is None
    auth.login("a@b.co", "password-123")
    assert metadata.find_user_by_email("a@b.co")["last_login_at"] is not None


# -------------------------------------------------------------- workspaces
def test_workspace_controller(metadata):
    c = WorkspaceController(metadata)
    wid = c.create("u1", "CV review", "desc")
    assert [str(w["_id"]) for w in c.list_for_user("u1")] == [wid]
    assert c.list_for_user("u2") == []
    for bad in ("", "   ", None):
        with pytest.raises(ValueError):
            c.create("u1", bad)


# ----------------------------------------------------------- conversations
def test_conversation_controller_scopes_by_workspace(metadata):
    c = ConversationController(metadata)
    a = c.create("u1", "w1", "A")
    b = c.create("u1", "w2", "B")
    assert {str(x["_id"]) for x in c.list_for_user("u1")} == {a, b}
    assert [str(x["_id"]) for x in c.list_for_user("u1", workspace_id="w1")] == [a]
    c.delete("u1", a)
    assert [str(x["_id"]) for x in c.list_for_user("u1")] == [b]


def test_conversation_controller_rename_and_clear(metadata):
    c = ConversationController(metadata)
    cid = c.create("u1", "w1", "New conversation")
    metadata.append_message("u1", cid, "user", "hi")
    c.rename("u1", cid, "Greeting")
    c.clear("u1", cid)
    assert metadata.get_conversation("u1", cid)["title"] == "Greeting"
    assert c.messages("u1", cid) == []


# -------------------------------------------------------------------- chat
class FakeWorkflow:
    def __init__(self, answer="the answer", error=None):
        self.answer, self.error, self.calls = answer, error, []

    def __call__(self, **kw):
        self.calls.append(kw)
        if self.error:
            raise self.error
        return {"answer": self.answer, "citations": ["c1"], "source_types": ["local"]}


def test_chat_persists_both_turns_and_passes_history(metadata):
    cid = metadata.create_conversation("u1", "w1", "T")
    wf = FakeWorkflow()
    chat = ChatController(metadata, workflow=wf)
    out = chat.send_message("u1", cid, " first question ", project_id="w1", ncbi_email="x@y.co")
    assert out["answer"] == "the answer"
    msgs = metadata.get_messages("u1", cid)
    assert [(m["role"], m["content"]) for m in msgs] == [("user", " first question "), ("assistant", "the answer")] or \
           [(m["role"], m["content"].strip()) for m in msgs] == [("user", "first question"), ("assistant", "the answer")]
    assert msgs[1]["citations"] == ["c1"] and msgs[1]["source_types"] == ["local"]
    call = wf.calls[0]
    assert call["project_id"] == "w1" and call["ncbi_email"] == "x@y.co" and call["user_id"] == "u1"
    assert call["history"][-1]["content"].strip() == "first question"

    chat.send_message("u1", cid, "second", project_id="w1")
    assert len(wf.calls[1]["history"]) == 3        # q1, a1, q2


@pytest.mark.parametrize("msg", ["", "   ", "\n"])
def test_chat_rejects_blank_messages(metadata, msg):
    cid = metadata.create_conversation("u1", "w", "T")
    with pytest.raises(ValueError):
        ChatController(metadata, workflow=FakeWorkflow()).send_message("u1", cid, msg)
    assert metadata.get_messages("u1", cid) == []


def test_chat_requires_a_workflow(metadata):
    cid = metadata.create_conversation("u1", "w", "T")
    with pytest.raises(RuntimeError):
        ChatController(metadata).send_message("u1", cid, "hi")


def test_chat_blocks_foreign_conversations(metadata):
    cid = metadata.create_conversation("owner", "w", "T")
    wf = FakeWorkflow()
    with pytest.raises(PermissionError):
        ChatController(metadata, workflow=wf).send_message("intruder", cid, "hi")
    assert wf.calls == []


def test_workflow_error_does_not_leave_a_dangling_question(metadata):
    """If the model fails, the user's question must not stay in history without an answer
    (otherwise the next request sends two consecutive user turns to the LLM)."""
    cid = metadata.create_conversation("u1", "w", "T")
    chat = ChatController(metadata, workflow=FakeWorkflow(error=RuntimeError("llm down")))
    with pytest.raises(RuntimeError):
        chat.send_message("u1", cid, "will fail")
    roles = [m["role"] for m in metadata.get_messages("u1", cid)]
    assert roles == [] or roles[-1] == "assistant"


def test_first_message_names_the_conversation(metadata):
    cid = metadata.create_conversation("u1", "w", "New conversation")
    ChatController(metadata, workflow=FakeWorkflow()).send_message("u1", cid, "What is metformin used for in practice?")
    assert metadata.get_conversation("u1", cid)["title"] == "What is metformin used for in practice?"
    ChatController(metadata, workflow=FakeWorkflow()).send_message("u1", cid, "another question")
    assert metadata.get_conversation("u1", cid)["title"] == "What is metformin used for in practice?"


def test_long_first_message_title_is_shortened(metadata):
    cid = metadata.create_conversation("u1", "w", "New conversation")
    ChatController(metadata, workflow=FakeWorkflow()).send_message("u1", cid, "word " * 60)
    title = metadata.get_conversation("u1", cid)["title"]
    assert len(title) <= 60 and title.endswith("…")
