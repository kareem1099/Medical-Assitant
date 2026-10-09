"""Whole-app journeys: real LangGraph workflow + real handlers + in-memory Mongo/Qdrant.

Only the LLM (scripted) and PubMed's network calls are replaced.
"""
import io

import pytest

from db import qdrant_client
from graph.workflow import create_workflow
from tests.conftest import tool_call_message
from tests.unit.test_pubmed_tool import EFETCH, ESEARCH
from tests.ui.test_layout_wiring import run as call
from tools import pubmed_tool
from ui.gradio_app import create_gradio_interface

pytestmark = pytest.mark.integration


@pytest.fixture
def demo(storage, fake_llm, monkeypatch):
    pubmed_tool.clear_pubmed_cache()
    monkeypatch.setattr(pubmed_tool.Entrez, "esearch",
                        lambda **kw: io.BytesIO(ESEARCH.format(n=2, ids="<Id>111</Id><Id>222</Id>").encode()))
    monkeypatch.setattr(pubmed_tool.Entrez, "efetch", lambda **kw: io.BytesIO(EFETCH.encode()))
    return create_gradio_interface(create_workflow())


def register(demo):
    out = call(demo, "register", "Kareem", "k@x.co", "password-123")
    return out[0], out[5], out[8]


def ask(demo, uid, project, session, text, history=None, email="me@example.com"):
    return call(demo, "send_message", text, history or [], project, email, uid, session)


def test_document_question_cites_the_right_file_and_page(demo, fake_llm, diabetes_pdf):
    uid, project, session = register(demo)
    status, *_ = call(demo, "upload_pdf", diabetes_pdf, project, uid)
    assert status.startswith("✅")

    fake_llm.replies = ["Give 15 g of fast-acting carbohydrate [diabetes_protocol.pdf, Page 2]."]
    _, chat, sources, _, _ = ask(demo, uid, project, session,
                                 "According to the uploaded document, how do we treat hypoglycemia with fast acting carbohydrate?")
    assert "15 g" in chat[-1][1] and "Disclaimer" in chat[-1][1]
    assert "diabetes_protocol.pdf, p. 2" in sources

    # persisted: reopening the conversation restores both the chat and the sources panel
    _, restored_chat, restored_sources = call(demo, "load_conversation", uid, session)
    assert restored_chat == chat and "diabetes_protocol.pdf, p. 2" in restored_sources


def test_follow_up_question_keeps_context(demo, fake_llm, diabetes_pdf):
    uid, project, session = register(demo)
    call(demo, "upload_pdf", diabetes_pdf, project, uid)
    fake_llm.replies = ["Metformin is first line [diabetes_protocol.pdf, Page 1]."]
    _, chat, *_ = ask(demo, uid, project, session, "According to the uploaded document what is the first line medication?")
    fake_llm.replies = [tool_call_message(), "It is checked every three months."]
    ask(demo, uid, project, session, "how often is HbA1c checked?", history=chat)
    sent_to_llm = " ".join(m.content for call_ in fake_llm.calls for m in call_)
    assert "first line medication" in sent_to_llm          # earlier turn visible in later prompts


def test_pubmed_question_links_the_paper(demo, fake_llm):
    uid, project, session = register(demo)
    fake_llm.replies = [tool_call_message(("search_pubmed", {"query": "metformin"})), "Evidence summary."]
    ask(demo, uid, project, session, "latest research on metformin")
    sources = call(demo, "load_conversation", uid, session)[2]
    assert "https://pubmed.ncbi.nlm.nih.gov/111/" in sources and "Metformin in type 2 diabetes" in sources


def test_pubmed_without_email_still_answers(demo, fake_llm):
    uid, project, session = register(demo)
    fake_llm.replies = [tool_call_message(("search_pubmed", {"query": "metformin"})), "General answer."]
    _, chat, sources, *_ = ask(demo, uid, project, session, "latest research on metformin", email="")
    assert "General answer." in chat[-1][1] and "No documents or papers" in sources


def test_users_cannot_see_each_others_documents_through_the_whole_stack(demo, fake_llm, diabetes_pdf):
    alice, a_project, a_session = register(demo)
    call(demo, "upload_pdf", diabetes_pdf, a_project, alice)
    bob = call(demo, "register", "Bob", "b@x.co", "password-123")
    bob_id, bob_project, bob_session = bob[0], bob[5], bob[8]
    fake_llm.replies = ["I could not find that in your documents."]
    _, chat, sources, *_ = ask(demo, bob_id, bob_project, bob_session,
                               "According to the uploaded document what is the first line medication metformin?")
    assert "diabetes_protocol.pdf" not in sources
    assert "No relevant information" in fake_llm.calls[-1][-1].content


def test_replace_then_delete_leaves_no_orphans(demo, storage, diabetes_pdf):
    uid, project, _ = register(demo)
    call(demo, "upload_pdf", diabetes_pdf, project, uid)
    call(demo, "upload_pdf", diabetes_pdf, project, uid)
    n = storage["mongo"].chunks.count_documents({})
    assert n == qdrant_client.get_collection_stats()["points_count"] > 0
    call(demo, "delete_workspace", project, uid, True)
    assert storage["mongo"].chunks.count_documents({}) == 0
    assert qdrant_client.get_collection_stats()["points_count"] == 0
