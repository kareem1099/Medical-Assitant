import pytest

from db import mongo_client, qdrant_client
from tools.pdf_loader import process_pdf_for_project
from tests.ui.conftest import val

# register/login tuple layout: user_id, auth_panel, app_panel, auth_status, welcome, *ctx
# ctx layout: project, project_dd, conversation_dd, session, chatbot, sources, files, file_select
USER, AUTH_PANEL, APP_PANEL, STATUS, WELCOME = range(5)
PROJECT, PROJECT_DD, CONV_DD, SESSION, CHAT, SOURCES, FILES, FILE_SELECT = range(5, 13)


def verify(h, out):
    """Accounts must confirm their email before they can sign in again."""
    h.auth.metadata.mark_email_verified(out[USER])


def test_register_signs_in_and_creates_a_ready_workspace(h):
    out = h.register(" Kareem ", "Kareem@Example.com", "password-123")
    assert out[USER] and val(out[AUTH_PANEL], "visible") is False and val(out[APP_PANEL], "visible") is True
    assert "Kareem" in out[WELCOME]
    assert out[PROJECT] and val(out[PROJECT_DD]) == out[PROJECT]
    assert [name for name, _ in val(out[PROJECT_DD], "choices")] == ["My first workspace"]
    assert out[SESSION] and val(out[CONV_DD]) == out[SESSION]
    assert out[CHAT] == []


@pytest.mark.parametrize("name,email,password,needle", [
    ("A", "not-an-email", "password-123", "valid email"),
    ("A", "a@b.co", "short", "8 characters"),
    ("  ", "a@b.co", "password-123", "Display name"),
])
def test_register_errors_keep_the_sign_in_screen(h, name, email, password, needle):
    out = h.register(name, email, password)
    assert out[USER] is None and val(out[AUTH_PANEL], "visible") is True and val(out[APP_PANEL], "visible") is False
    assert needle in out[STATUS] and out[STATUS].startswith("❌")


def test_register_duplicate_email(h):
    verify(h, h.register("A", "a@b.co", "password-123"))
    assert "already exists" in h.register("B", "A@B.CO", "password-123")[STATUS]


def test_login_success_and_failure_messages(h):
    verify(h, h.register("Kareem", "k@x.co", "password-123"))
    ok = h.login("k@x.co", "password-123")
    assert ok[USER] and ok[PROJECT] and ok[SESSION]
    bad = h.login("k@x.co", "wrong-password")
    assert bad[USER] is None and "Invalid email or password" in bad[STATUS]
    assert "valid email" in h.login("nope", "x")[STATUS]
    assert h.login("k@x.co", None)[USER] is None            # empty password must not crash


def test_login_reuses_existing_conversation_instead_of_creating_new_ones(h):
    verify(h, h.register("K", "k@x.co", "password-123"))
    first = h.login("k@x.co", "password-123")
    second = h.login("k@x.co", "password-123")
    assert first[SESSION] == second[SESSION]
    assert len(val(second[CONV_DD], "choices")) == 1


def test_logout_resets_everything(h):
    out = h.logout()
    assert out[USER] is None and val(out[AUTH_PANEL], "visible") is True and val(out[APP_PANEL], "visible") is False
    assert out[CHAT] == [] and val(out[PROJECT_DD], "choices") == []


def test_backend_outage_during_login_shows_generic_message(h, monkeypatch):
    monkeypatch.setattr(h.auth, "login", lambda *a: (_ for _ in ()).throw(ConnectionError("mongodb://secret-host down")))
    out = h.login("k@x.co", "password-123")
    assert "secret-host" not in out[STATUS] and "went wrong" in out[STATUS]


# ----------------------------------------------------------------- workspaces
# create_workspace: status, name_box, desc_box, *ctx
C_STATUS, C_NAME, C_DESC = range(3)
CP, CPDD, CCONV, CSESS, CCHAT, CSRC, CFILES, CFSEL = range(3, 11)


def test_create_workspace_selects_it_and_starts_a_conversation(signed_in):
    h, uid, first_project, first_session = signed_in
    out = h.create_workspace("  Cardiology ", "heart stuff", uid)
    assert "Created" in out[C_STATUS] and out[C_NAME] == "" and out[C_DESC] == ""
    assert out[CP] != first_project and val(out[CPDD]) == out[CP]
    assert out[CSESS] != first_session and out[CCHAT] == []
    names = [n for n, _ in val(out[CPDD], "choices")]
    assert names == ["Cardiology", "My first workspace"]


@pytest.mark.parametrize("name", ["", "   ", None])
def test_create_workspace_requires_name(signed_in, name):
    h, uid, project, _ = signed_in
    out = h.create_workspace(name, "", uid)
    assert out[C_STATUS].startswith("❌") and out[CP] == project


def test_create_workspace_requires_login(h):
    assert h.create_workspace("X", "", None)[C_STATUS].startswith("❌")


def test_select_workspace_switches_documents_and_conversations(signed_in, diabetes_pdf):
    h, uid, p1, s1 = signed_in
    p2 = h.create_workspace("Second", "", uid)[CP]
    process_pdf_for_project(diabetes_pdf, p1, user_id=uid)
    ctx = h.select_workspace(p1, uid)
    assert ctx[0] == p1 and ctx[3] == s1 and "diabetes_protocol.pdf" in ctx[6]
    ctx2 = h.select_workspace(p2, uid)
    assert ctx2[0] == p2 and "No documents yet" in ctx2[6] and ctx2[3] != s1


def test_selecting_someone_elses_workspace_falls_back_to_own(signed_in):
    h, uid, own, _ = signed_in
    other_uid = h.register("O", "o@x.co", "password-123")[USER]
    foreign = mongo_client.list_projects(user_id=other_uid)[0]["id"]
    assert h.select_workspace(foreign, uid)[0] == own


def test_conversation_list_is_scoped_to_the_selected_workspace(signed_in):
    h, uid, p1, s1 = signed_in
    p2 = h.create_workspace("Second", "", uid)[CP]
    ids_in_p1 = [v for _, v in val(h.select_workspace(p1, uid)[2], "choices")]
    ids_in_p2 = [v for _, v in val(h.select_workspace(p2, uid)[2], "choices")]
    assert s1 in ids_in_p1 and s1 not in ids_in_p2


def test_conversations_without_a_workspace_are_not_listed_for_all_workspaces(h):
    assert h.conversation_choices("u1", None) == []


# --------------------------------------------------------------- delete workspace
def test_delete_workspace_needs_confirmation(signed_in):
    h, uid, project, _ = signed_in
    out = h.delete_workspace(project, uid, False)
    assert "confirm" in out[0].lower() and mongo_client.get_project(project) is not None


def test_delete_workspace_removes_everything(signed_in, diabetes_pdf):
    h, uid, project, session = signed_in
    keep = h.create_workspace("Keep", "", uid)[CP]
    process_pdf_for_project(diabetes_pdf, project, user_id=uid)
    h.metadata.append_message(uid, session, "user", "hi")
    out = h.delete_workspace(project, uid, True)
    assert "Deleted workspace" in out[0] and out[1] is False
    assert out[2] == keep                                      # lands on a workspace that still exists
    assert mongo_client.get_project(project) is None
    assert qdrant_client.get_collection_stats()["points_count"] == 0
    assert h.metadata.chat_sessions.count_documents({"workspace_id": project}) == 0
    assert h.metadata.chat_messages.count_documents({"session_id": session}) == 0


def test_cannot_delete_someone_elses_workspace(signed_in):
    h, uid, project, _ = signed_in
    other = h.register("O", "o@x.co", "password-123")
    out = h.delete_workspace(other[PROJECT], uid, True)
    assert out[0].startswith("❌") and mongo_client.get_project(other[PROJECT]) is not None
