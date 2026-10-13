"""HTTP-level tests for the web API (FastAPI TestClient, in-memory stores, stub workflow)."""
import json
import re
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from api.server import create_app, safe_filename
from api.sessions import COOKIE_NAME, SessionSigner
from config.settings import settings
from src.controllers import AuthController

LOCAL_OUTPUT = """=== Local Document Search Results ===

Chunk 1:
Source: diabetes_protocol.pdf
Page: 2
Relevance: 0.61
Content: metformin first line
"""


class StreamingWorkflow:
    """Mimics the compiled graph's ``stream(..., stream_mode="updates")``."""

    def __init__(self):
        self.calls = []
        self.tools = []
        self.answer = "Stub answer."
        self.tool_outputs = []
        self.failed = False
        self.error = None

    def stream(self, inputs, config=None, stream_mode=None):
        self.calls.append({"inputs": inputs, "config": config})
        if self.error:
            raise self.error
        calls = [{"name": t, "args": {}, "id": t, "type": "tool_call"} for t in self.tools]
        yield {"agent": {"messages": [AIMessage(content="", tool_calls=calls)]}}
        if self.tools:
            yield {"tools": {"messages": []}}
        yield {"final_response": {"final_answer": self.answer, "tool_outputs": self.tool_outputs,
                                  "failed": self.failed}}


@pytest.fixture
def workflow():
    return StreamingWorkflow()


class FakeMailer:
    def __init__(self):
        self.sent = []

    def send(self, to, subject, body):
        self.sent.append({"to": to, "subject": subject, "body": body})

    def code(self, to):
        """The code in the latest email to ``to``."""
        mail = next(m for m in reversed(self.sent) if m["to"] == to)
        return re.search(r"\b\d{6}\b", mail["body"]).group()


class FakeGoogle:
    """Stands in for Google's token check: the test credential is ``sub|email|name``."""

    def verify(self, credential):
        if credential.count("|") != 2:
            raise ValueError("Wrong number of segments in token")
        sub, email, name = credential.split("|")
        return {"sub": sub, "email": email, "name": name}


@pytest.fixture
def mailer():
    return FakeMailer()


@pytest.fixture
def app(storage, metadata, workflow, mailer, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>SPA</title>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    app = create_app(workflow, metadata, static_dir=dist, mailer=mailer, google=FakeGoogle())
    app.state.mailer = mailer
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


def register(client, email="k@x.co", name="Kareem"):
    """Sign up with Google - the user ends up signed in."""
    r = client.post("/api/auth/google", json={"credential": f"sub-{email}|{email}|{name}"})
    assert r.status_code == 200, r.text
    return r.json()["user"]


def set_password(client, email="k@x.co", password="password-123"):
    """Give an account a password through the forgot-password flow."""
    client.post("/api/auth/forgot-password", json={"email": email})
    code = client.app.state.mailer.code(email)
    r = client.post("/api/auth/reset-password", json={"email": email, "code": code, "password": password})
    assert r.status_code == 200, r.text


@pytest.fixture
def signed_in(client):
    user = register(client)
    ws = client.get("/api/workspaces").json()[0]
    conv = client.post(f"/api/workspaces/{ws['id']}/conversations").json()
    return client, user, ws, conv


def ask(client, conv_id, message="What is hypertension?", email=""):
    r = client.post(f"/api/conversations/{conv_id}/messages", json={"message": message, "ncbi_email": email})
    if r.status_code != 200:
        return r, []
    return r, [json.loads(line) for line in r.text.splitlines() if line.strip()]


# ------------------------------------------------------------------- auth
def test_google_sign_up_signs_in_with_http_only_cookie_and_creates_a_workspace(client, metadata):
    r = client.post("/api/auth/google", json={"credential": "g-1|K@X.co|Kareem"})
    assert r.status_code == 200 and r.json()["user"]["email"] == "k@x.co"
    assert "httponly" in r.headers["set-cookie"].lower() and "samesite=lax" in r.headers["set-cookie"].lower()
    assert client.get("/api/auth/me").json()["user"]["display_name"] == "Kareem"
    assert [w["name"] for w in client.get("/api/workspaces").json()] == ["My first workspace"]
    user = metadata.users.find_one({"email": "k@x.co"})
    assert user["email_verified"] is True and user["password_hash"] is None and user["google_sub"] == "g-1"


def test_google_sign_in_again_reuses_the_account(client, metadata):
    first = register(client)
    client.post("/api/auth/logout")
    second = client.post("/api/auth/google", json={"credential": "sub-k@x.co|k@x.co|Renamed"}).json()["user"]
    assert first == second and metadata.users.count_documents({}) == 1
    assert len(client.get("/api/workspaces").json()) == 1


def test_bad_google_token_is_rejected(client):
    r = client.post("/api/auth/google", json={"credential": "forged"})
    assert r.status_code == 401 and client.get("/api/auth/me").status_code == 401


def test_password_sign_up_is_gone(client):
    body = {"display_name": "A", "email": "a@b.co", "password": "password-123"}
    assert client.post("/api/auth/register", json=body).status_code == 404


def test_google_takes_over_an_unverified_address_and_drops_its_password(client, metadata):
    AuthController(metadata).register("k@x.co", "attacker-pass", "Squatter")
    assert client.post("/api/auth/login", json={"email": "k@x.co", "password": "attacker-pass"}).status_code == 403
    register(client)
    client.post("/api/auth/logout")
    assert metadata.users.count_documents({}) == 1
    assert client.post("/api/auth/login", json={"email": "k@x.co", "password": "attacker-pass"}).status_code == 401


def test_google_user_has_no_password_until_they_set_one(client):
    register(client)
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"email": "k@x.co", "password": "anything-at-all"}).status_code == 401
    set_password(client)
    client.post("/api/auth/logout")
    r = client.post("/api/auth/login", json={"email": "k@x.co", "password": "nope-nope-nope"})
    assert r.status_code == 401 and r.json()["detail"] == "Invalid email or password"
    assert client.post("/api/auth/login", json={"email": "k@x.co", "password": "password-123"}).status_code == 200


def test_forgot_and_reset_password(app, client, mailer):
    register(client)
    set_password(client, password="password-123")
    other_device = TestClient(app)
    other_device.post("/api/auth/login", json={"email": "k@x.co", "password": "password-123"})
    assert other_device.get("/api/auth/me").status_code == 200

    sent = len(mailer.sent)
    assert client.post("/api/auth/forgot-password", json={"email": "ghost@x.co"}).json() == {"ok": True}
    assert len(mailer.sent) == sent                                  # nobody to email, same answer
    mailer.sent.clear()
    assert client.post("/api/auth/forgot-password", json={"email": "K@x.co"}).json() == {"ok": True}
    assert [m["to"] for m in mailer.sent] == ["k@x.co"]               # any case finds the account


def test_reset_code_is_single_use_limited_and_rejects_weak_passwords(client, mailer, metadata):
    register(client)
    client.post("/api/auth/forgot-password", json={"email": "k@x.co"})
    code = mailer.code("k@x.co")
    assert "Reset" in mailer.sent[-1]["subject"]
    weak = client.post("/api/auth/reset-password", json={"email": "k@x.co", "code": code, "password": "short"})
    assert weak.status_code == 400
    r = client.post("/api/auth/reset-password", json={"email": "k@x.co", "code": code, "password": "brand-new-pass"})
    assert r.status_code == 200 and client.get("/api/auth/me").status_code == 200
    again = client.post("/api/auth/reset-password", json={"email": "k@x.co", "code": code, "password": "another-pass"})
    assert again.status_code == 400

    metadata.users.update_one({"email": "k@x.co"}, {"$set": {"codes.reset.sent_at": datetime(2000, 1, 1)}})
    client.post("/api/auth/forgot-password", json={"email": "k@x.co"})
    good = mailer.code("k@x.co")
    bad = "000000" if good != "000000" else "111111"
    for _ in range(5):
        body = {"email": "k@x.co", "code": bad, "password": "password-999"}
        assert client.post("/api/auth/reset-password", json=body).status_code == 400
    locked = client.post("/api/auth/reset-password", json={"email": "k@x.co", "code": good, "password": "password-999"})
    assert locked.status_code == 400


def test_reset_ends_sessions_started_before_it(client, metadata):
    register(client)
    metadata.users.update_one({"email": "k@x.co"}, {"$set": {"password_changed_at": datetime.utcnow() + timedelta(seconds=5)}})
    assert client.get("/api/auth/me").status_code == 401


def test_logout_and_anonymous_access(client):
    register(client)
    client.post("/api/auth/logout")
    for path in ("/api/auth/me", "/api/workspaces"):
        assert client.get(path).status_code == 401


def test_tampered_or_expired_cookie_is_rejected(client):
    user = register(client)
    good = client.cookies.get(COOKIE_NAME)
    uid, expires, sig = good.split(".")
    client.cookies.set(COOKIE_NAME, f"{uid}.{int(expires) + 999}.{sig}")
    assert client.get("/api/auth/me").status_code == 401
    signer = SessionSigner("s", lifetime=10)
    assert signer.verify(signer.issue(user["id"], now=0), now=5) == user["id"]
    assert signer.verify(signer.issue(user["id"], now=0), now=11) is None
    assert signer.verify("garbage") is None and signer.verify(None) is None


# ------------------------------------------------------- isolation per user
def test_users_cannot_touch_each_others_data(app, signed_in):
    _, _, ws, conv = signed_in
    other = TestClient(app)
    register(other, email="other@x.co")
    assert other.get(f"/api/workspaces/{ws['id']}/files").status_code == 404
    assert other.get(f"/api/workspaces/{ws['id']}/conversations").status_code == 404
    assert other.get(f"/api/conversations/{conv['id']}/messages").status_code == 404
    assert ask(other, conv["id"])[0].status_code == 404
    assert other.delete(f"/api/workspaces/{ws['id']}").status_code == 404
    assert other.get("/api/conversations/not-an-id/messages").status_code == 404


# -------------------------------------------------------------- workspaces
def test_workspace_lifecycle(signed_in, diabetes_pdf):
    client, _, ws, conv = signed_in
    assert client.post("/api/workspaces", json={"name": "  "}).status_code == 400
    new = client.post("/api/workspaces", json={"name": "Cardio", "description": "notes"}).json()
    assert [w["name"] for w in client.get("/api/workspaces").json()] == ["Cardio", "My first workspace"]
    with open(diabetes_pdf, "rb") as f:
        client.post(f"/api/workspaces/{new['id']}/files", files={"file": ("p.pdf", f, "application/pdf")})
    client.post(f"/api/workspaces/{new['id']}/conversations")
    assert client.delete(f"/api/workspaces/{new['id']}").json()["name"] == "Cardio"
    assert client.get(f"/api/workspaces/{new['id']}/files").status_code == 404
    assert [w["name"] for w in client.get("/api/workspaces").json()] == ["My first workspace"]


# --------------------------------------------------------------- documents
def test_upload_list_replace_and_delete_a_pdf(signed_in, diabetes_pdf):
    client, _, ws, _ = signed_in
    url = f"/api/workspaces/{ws['id']}/files"
    with open(diabetes_pdf, "rb") as f:
        r = client.post(url, files={"file": ("diabetes_protocol.pdf", f, "application/pdf")})
    assert r.status_code == 201 and r.json()["num_chunks"] > 0 and not r.json()["replaced"]
    with open(diabetes_pdf, "rb") as f:
        assert client.post(url, files={"file": ("diabetes_protocol.pdf", f, "application/pdf")}).json()["replaced"]
    files = client.get(url).json()
    assert [(f["filename"], f["status"]) for f in files] == [("diabetes_protocol.pdf", "completed")]
    assert client.get("/api/workspaces").json()[0]["file_count"] == 1
    assert client.delete(f"{url}/{files[0]['id']}").json()["filename"] == "diabetes_protocol.pdf"
    assert client.get(url).json() == []
    assert client.delete(f"{url}/{files[0]['id']}").status_code == 404


def test_upload_rejects_non_pdf_corrupt_and_oversized_files(signed_in, monkeypatch):
    client, _, ws, _ = signed_in
    url = f"/api/workspaces/{ws['id']}/files"
    assert client.post(url, files={"file": ("notes.txt", b"hello", "text/plain")}).status_code == 400
    r = client.post(url, files={"file": ("broken.pdf", b"not a pdf", "application/pdf")})
    assert r.status_code == 422 and "broken.pdf" in r.json()["detail"]
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    big = b"%PDF-1.4\n" + b"0" * (1024 * 1024 + 10)
    assert client.post(url, files={"file": ("big.pdf", big, "application/pdf")}).status_code == 413


def test_safe_filename_keeps_arabic_and_strips_paths():
    assert safe_filename("../../etc/passwd.pdf") == "passwd.pdf"
    assert safe_filename("C:\\Users\\x\\بروتوكول السكري.pdf") == "بروتوكول السكري.pdf"
    assert safe_filename("a\x00b.pdf") == "ab.pdf"
    assert safe_filename("") == "document.pdf"


# ------------------------------------------------------------ conversations
def test_empty_conversation_is_reused_rename_clear_delete(signed_in):
    client, _, ws, conv = signed_in
    base = f"/api/workspaces/{ws['id']}/conversations"
    assert client.post(base).json()["id"] == conv["id"]
    ask(client, conv["id"])
    second = client.post(base).json()
    assert second["id"] != conv["id"]
    assert client.patch(f"/api/conversations/{conv['id']}", json={"title": "Renamed"}).json()["title"] == "Renamed"
    client.post(f"/api/conversations/{conv['id']}/clear")
    assert client.get(f"/api/conversations/{conv['id']}/messages").json() == []
    client.delete(f"/api/conversations/{second['id']}")
    assert [c["id"] for c in client.get(base).json()] == [conv["id"]]


# --------------------------------------------------------------------- chat
def test_chat_streams_real_stages_then_the_answer_and_persists_it(signed_in, workflow):
    client, user, ws, conv = signed_in
    workflow.tools = ["medical_rag_search"]
    workflow.tool_outputs = [{"tool": "medical_rag_search", "content": LOCAL_OUTPUT}]
    r, events = ask(client, conv["id"], "  What does our protocol say?  ", email=" me@x.co ")
    assert r.headers["content-type"].startswith("application/x-ndjson")
    assert [e.get("stage") for e in events[:-1]] == ["thinking", "searching", "writing"]
    assert events[1]["tools"] == ["medical_rag_search"]
    result = events[-1]
    assert result["type"] == "result" and result["answer"] == "Stub answer."
    assert result["sources"][0] == {"type": "local", "label": "diabetes_protocol.pdf, p. 2",
                                    "filename": "diabetes_protocol.pdf", "page": 2, "score": 0.61}
    assert result["conversation"]["title"] == "What does our protocol say?"
    cfg = workflow.calls[0]["config"]["configurable"]
    assert cfg == {"project_id": ws["id"], "ncbi_email": "me@x.co", "user_id": user["id"]}
    stored = client.get(f"/api/conversations/{conv['id']}/messages").json()
    assert [m["role"] for m in stored] == ["user", "assistant"]
    assert stored[1]["sources"][0]["filename"] == "diabetes_protocol.pdf"


def test_follow_up_sends_history(signed_in, workflow):
    client, _, _, conv = signed_in
    ask(client, conv["id"], "first")
    ask(client, conv["id"], "second")
    sent = [m.content for m in workflow.calls[1]["inputs"]["messages"]]
    assert sent == ["first", "Stub answer.", "second"]


def test_failed_answer_is_an_error_event_and_nothing_is_stored(signed_in, workflow):
    client, _, _, conv = signed_in
    workflow.failed = True
    _, events = ask(client, conv["id"])
    assert events[-1]["type"] == "error"
    workflow.failed, workflow.error = False, RuntimeError("cohere down: key=sk-secret")
    _, events = ask(client, conv["id"])
    assert events[-1]["type"] == "error" and "secret" not in events[-1]["message"]
    assert client.get(f"/api/conversations/{conv['id']}/messages").json() == []


def test_missing_ncbi_email_note(signed_in, workflow):
    client, _, _, conv = signed_in
    workflow.tools = ["search_pubmed"]
    workflow.tool_outputs = [{"tool": "search_pubmed", "content": "Error: A valid NCBI email is required."}]
    answer = ask(client, conv["id"], "recent research?")[1][-1]["answer"]
    assert answer.startswith("Stub answer.") and "NCBI email" in answer


@pytest.mark.parametrize("message,email,status", [("   ", "", 400), ("hi", "bad-email", 400), ("x" * 4001, "", 422)])
def test_chat_input_validation(signed_in, message, email, status):
    client, _, _, conv = signed_in
    assert ask(client, conv["id"], message, email)[0].status_code == status


def test_messages_saved_before_structured_sources_still_render(signed_in, metadata):
    client, user, _, conv = signed_in
    metadata.append_message(user["id"], conv["id"], "user", "q")
    metadata.append_message(user["id"], conv["id"], "assistant", "a", ["old.pdf, p. 1"], ["local"])
    assert client.get(f"/api/conversations/{conv['id']}/messages").json()[1]["sources"] == [
        {"type": "local", "label": "old.pdf, p. 1"}]


# --------------------------------------------------------------- front-end
def test_spa_is_served_with_history_fallback_and_api_404s_stay_json(client):
    assert "SPA" in client.get("/").text
    assert "SPA" in client.get("/some/client/route").text
    assert client.get("/assets/app.js").text == "console.log(1)"
    r = client.get("/api/nope")
    assert r.status_code == 404 and r.json()["detail"] == "Not found."
    assert "SPA" in client.get("/../../etc/passwd").text
