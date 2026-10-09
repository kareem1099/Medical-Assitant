import pytest

from tests.ui.conftest import val
from ui.handlers import (THINKING, files_markdown, messages_to_history, normalize_id,
                         sources_from_messages)

LOCAL_OUTPUT = """=== Local Document Search Results ===

Chunk 1:
Source: diabetes_protocol.pdf
Page: 2
Relevance: 0.83
Content: give 15 grams
"""
PUBMED_OUTPUT = """=== PubMed Search Results ===

Paper 1:
Title: Metformin meta-analysis.
Journal: Diabetes Care
Date: 2023-Sep
PMID: 111
Abstract: x
"""


def send(h, uid, project, session, text, history=None, email=""):
    return list(h.send_message(text, history or [], project, email, uid, session))


# ----------------------------------------------------------------- send_message
def test_send_streams_a_waiting_state_then_the_answer(signed_in, workflow):
    h, uid, project, session = signed_in
    steps = send(h, uid, project, session, "  What is hypertension?  ")
    assert len(steps) == 2
    box, chat, _, _, _ = steps[0]
    assert box == "" and chat == [["What is hypertension?", THINKING]]      # shown immediately, input cleared
    box, chat, sources, sess, conv_dd = steps[1]
    assert chat == [["What is hypertension?", "Stub answer."]] and sess == session
    assert "No documents or papers were needed" in sources
    assert val(conv_dd) == session


def test_turn_is_persisted_and_conversation_is_named_after_the_question(signed_in):
    h, uid, project, session = signed_in
    send(h, uid, project, session, "What is hypertension?")
    assert [m["role"] for m in h.metadata.get_messages(uid, session)] == ["user", "assistant"]
    assert h.metadata.get_conversation(uid, session)["title"] == "What is hypertension?"
    labels = [n for n, _ in val(send(h, uid, project, session, "and treatment?")[-1][4], "choices")]
    assert labels == ["What is hypertension?"]


def test_sources_come_from_the_tools_that_actually_ran(signed_in, workflow):
    h, uid, project, session = signed_in
    workflow.tool_outputs = [{"tool": "medical_rag_search", "content": LOCAL_OUTPUT},
                             {"tool": "search_pubmed", "content": PUBMED_OUTPUT}]
    sources = send(h, uid, project, session, "compare")[-1][2]
    assert "diabetes_protocol.pdf, p. 2" in sources
    assert "https://pubmed.ncbi.nlm.nih.gov/111/" in sources


def test_brackets_in_the_answer_are_not_mistaken_for_citations(signed_in, workflow):
    h, uid, project, session = signed_in
    workflow.answer = "Take [as directed] twice daily [see label]."
    assert "as directed" not in send(h, uid, project, session, "q")[-1][2]


def test_workflow_receives_ids_history_and_email(signed_in, workflow):
    h, uid, project, session = signed_in
    send(h, uid, project, session, "first")
    send(h, uid, project, session, "second", email=" me@example.com ")
    call = workflow.calls[-1]
    assert call["config"]["configurable"] == {"project_id": project, "ncbi_email": "me@example.com", "user_id": uid}
    assert [m.content for m in call["state"]["messages"]] == ["first", "Stub answer.", "second"]
    assert call["state"]["user_query"] == "second" and call["state"]["project_id"] == project


def test_blank_message_does_nothing(signed_in, workflow):
    h, uid, project, session = signed_in
    steps = send(h, uid, project, session, "   ", history=[["a", "b"]])
    assert len(steps) == 1 and steps[0][1] == [["a", "b"]] and workflow.calls == []


@pytest.mark.parametrize("who,expected", [("no_user", "sign in"), ("no_project", "workspace")])
def test_missing_prerequisites_explain_what_to_do(signed_in, workflow, who, expected):
    h, uid, project, session = signed_in
    args = (None, project, session) if who == "no_user" else (uid, None, None)
    steps = send(h, *args[:1], args[1], args[2], "hello")
    assert expected in steps[0][1][-1][1].lower() and workflow.calls == []
    assert steps[0][0] == "hello"                      # the typed question is kept, not lost


def test_invalid_ncbi_email_is_rejected_before_calling_the_model(signed_in, workflow):
    h, uid, project, session = signed_in
    steps = send(h, uid, project, session, "q", email="bad-email")
    assert "NCBI email" in steps[0][1][-1][1] and workflow.calls == []


def test_model_failure_shows_friendly_error_and_persists_nothing(signed_in, workflow):
    h, uid, project, session = signed_in
    workflow.error = RuntimeError("cohere key=sk-SECRET exploded")
    steps = send(h, uid, project, session, "q")
    shown = steps[-1][1][-1][1]
    assert "couldn't complete" in shown and "SECRET" not in shown
    assert h.metadata.get_messages(uid, session) == []
    workflow.error = None
    assert send(h, uid, project, session, "q again")[-1][1][-1][1] == "Stub answer."   # next request works


def test_cannot_write_into_someone_elses_conversation(signed_in, workflow):
    h, uid, project, session = signed_in
    other = h.register("O", "o@x.co", "password-123")
    steps = send(h, other[0], other[5], session, "hijack")
    assert "not available" in steps[-1][1][-1][1] and workflow.calls == []
    assert h.metadata.get_messages(uid, session) == []


# ---------------------------------------------------------------- conversations
def test_new_conversation_reuses_an_empty_one(signed_in):
    h, uid, project, session = signed_in
    out = h.new_conversation(uid, project)
    assert out[1] == session and len(val(out[0], "choices")) == 1
    send(h, uid, project, session, "hello")
    out2 = h.new_conversation(uid, project)
    assert out2[1] != session and out2[2] == []
    assert len(val(out2[0], "choices")) == 2


def test_new_conversation_needs_a_workspace(h):
    out = h.new_conversation("u", None)
    assert out[1] is None and "workspace" in out[3].lower()


def test_load_conversation_restores_chat_and_sources(signed_in, workflow):
    h, uid, project, session = signed_in
    workflow.tool_outputs = [{"tool": "medical_rag_search", "content": LOCAL_OUTPUT}]
    send(h, uid, project, session, "q1")
    sid, chat, sources = h.load_conversation(uid, session)
    assert sid == session and chat == [["q1", "Stub answer."]] and "diabetes_protocol.pdf" in sources


def test_load_conversation_tolerates_bad_input(signed_in):
    h, uid, _, _ = signed_in
    for bad in (None, "", "garbage", "64b64b64b64b64b64b64b64b"):
        sid, chat, sources = h.load_conversation(uid, bad)
        assert chat == [] and "Ask a question" in sources
    other = h.register("O", "o@x.co", "password-123")
    assert h.load_conversation(other[0], signed_in[3])[1] == []        # not theirs -> empty, no crash


def test_delete_conversation_selects_a_remaining_one_or_creates_fresh(signed_in):
    h, uid, project, s1 = signed_in
    send(h, uid, project, s1, "keep me")
    s2 = h.new_conversation(uid, project)[1]
    dd, sid, chat, _ = h.delete_conversation(uid, s2, project)
    assert sid == s1 and chat and len(val(dd, "choices")) == 1
    dd, sid, chat, _ = h.delete_conversation(uid, s1, project)
    assert sid and sid != s1 and chat == []                              # a fresh empty conversation


def test_clear_conversation_really_clears_the_stored_history(signed_in):
    h, uid, project, session = signed_in
    send(h, uid, project, session, "q")
    chat, sources = h.clear_conversation(uid, session)
    assert chat == [] and h.metadata.get_messages(uid, session) == []
    assert h.load_conversation(uid, session)[1] == []                    # does not come back on reload


# ---------------------------------------------------------------------- helpers
def test_messages_to_history_pairs_turns_and_keeps_unanswered_questions():
    msgs = [{"role": "user", "content": "q1"}, {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"}]
    assert messages_to_history(msgs) == [["q1", "a1"], ["q2", None]]
    assert messages_to_history([]) == []


def test_sources_from_messages_uses_latest_answer_with_sources():
    msgs = [{"role": "assistant", "content": "a", "citations": ["old.pdf, p. 1"], "source_types": ["local"]},
            {"role": "assistant", "content": "b", "citations": [], "source_types": []}]
    assert "old.pdf" in sources_from_messages(msgs)


@pytest.mark.parametrize("raw,expected", [(None, None), ("", None), ("abc", "abc"), ({"id": "x"}, "x"),
                                           (("label", "x"), "x"), (["x"], "x"), ({}, None)])
def test_normalize_id(raw, expected):
    assert normalize_id(raw) == expected


def test_files_markdown_shows_status_and_escapes_pipes():
    md = files_markdown([
        {"filename": "a|b.pdf", "num_pages": 3, "num_chunks": 9, "status": "completed"},
        {"filename": "bad.pdf", "num_pages": 1, "num_chunks": 0, "status": "failed", "error_message": "no text"},
    ])
    assert "✅" in md and "❌" in md and "a\\|b.pdf" in md and "no text" in md
    assert "No documents yet" in files_markdown([])


def test_missing_ncbi_email_tells_the_user_how_to_enable_pubmed(signed_in, workflow):
    h, uid, project, session = signed_in
    workflow.tool_outputs = [{"tool": "search_pubmed",
                              "content": "Error: A valid NCBI email is required. Enter your email in the application before using PubMed."}]
    answer = send(h, uid, project, session, "recent research on SGLT2 inhibitors?")[-1][1][-1][1]
    assert "Stub answer." in answer and "NCBI email" in answer and "Settings" in answer


def test_no_pubmed_note_when_pubmed_ran(signed_in, workflow):
    h, uid, project, session = signed_in
    workflow.tool_outputs = [{"tool": "search_pubmed", "content": PUBMED_OUTPUT}]
    assert send(h, uid, project, session, "research?", email="me@example.com")[-1][1][-1][1] == "Stub answer."


def test_failed_generation_is_shown_as_error_and_not_saved(signed_in, workflow):
    h, uid, project, session = signed_in
    workflow.invoke = lambda state, config=None: {"final_answer": "I encountered an error...", "failed": True}
    answer = send(h, uid, project, session, "What is hypertension?")[-1][1][-1][1]
    assert answer.startswith("⚠️")
    assert h.metadata.get_messages(uid, session) == []
