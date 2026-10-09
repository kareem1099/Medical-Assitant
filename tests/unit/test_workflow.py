import io

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from graph.workflow import create_workflow, route_after_agent
from tests.conftest import tool_call_message
from tools import pubmed_tool
from tools.pdf_loader import process_pdf_for_project

from tests.unit.test_pubmed_tool import EFETCH, ESEARCH  # realistic XML fixtures


def invoke(wf, query, project="p1", user="u1", history=None, email="me@example.com"):
    return wf.invoke(
        {"messages": (history or []) + [HumanMessage(content=query)], "user_query": query, "project_id": project,
         "retrieved_docs": [], "pubmed_results": [], "tool_outputs": [], "final_answer": ""},
        config={"configurable": {"project_id": project, "user_id": user, "ncbi_email": email}},
    )


@pytest.fixture
def wf():
    return create_workflow()


@pytest.fixture(autouse=True)
def fake_pubmed(monkeypatch):
    pubmed_tool.clear_pubmed_cache()
    monkeypatch.setattr(pubmed_tool.Entrez, "esearch",
                        lambda **kw: io.BytesIO(ESEARCH.format(n=2, ids="<Id>111</Id><Id>222</Id>").encode()))
    monkeypatch.setattr(pubmed_tool.Entrez, "efetch", lambda **kw: io.BytesIO(EFETCH.encode()))


def test_graph_shape(wf):
    nodes = set(wf.get_graph().nodes)
    assert {"agent", "tools", "final_response"} <= nodes


def test_route_after_agent():
    with_tools = {"messages": [tool_call_message(("search_pubmed", {"query": "x"}))]}
    without = {"messages": [AIMessage(content="direct")]}
    assert route_after_agent(with_tools) == "tools"
    assert route_after_agent(without) == "final_response"


def test_direct_answer_path_calls_no_tools(wf, fake_llm):
    fake_llm.replies = [AIMessage(content="no tools needed"), "Hypertension means high blood pressure."]
    out = invoke(wf, "What is hypertension?", project="")
    assert "high blood pressure" in out["final_answer"]
    assert out["tool_outputs"] == [] and len(fake_llm.calls) == 2


def test_pubmed_path(wf, fake_llm):
    fake_llm.replies = [tool_call_message(("search_pubmed", {"query": "metformin"})), "Evidence summary [Diabetes Care]."]
    out = invoke(wf, "latest metformin research")
    final_prompt = fake_llm.calls[-1][-1].content
    assert "Metformin in type 2 diabetes" in final_prompt and "PMID: 111" in final_prompt
    assert [o["tool"] for o in out["tool_outputs"]] == ["search_pubmed"]


def test_pubmed_without_email_degrades_gracefully(wf, fake_llm):
    fake_llm.replies = [tool_call_message(("search_pubmed", {"query": "metformin"})), "General answer."]
    out = invoke(wf, "latest metformin research", email="")
    assert "valid NCBI email" in fake_llm.calls[-1][-1].content
    assert out["final_answer"]


def test_local_rag_path_end_to_end(wf, fake_llm, storage, diabetes_pdf):
    process_pdf_for_project(diabetes_pdf, "p1", user_id="u1")
    fake_llm.replies = ["Give 15 grams of carbohydrate [diabetes_protocol.pdf, Page 2]."]
    out = invoke(wf, "According to the uploaded document, how is hypoglycemia treated with fast acting carbohydrate?")
    prompt = fake_llm.calls[-1][-1].content
    assert "15 grams" in prompt and "Page: 2" in prompt
    assert len(fake_llm.calls) == 1            # deterministic routing => only the synthesis call hit the LLM
    assert "15 grams" in out["final_answer"]


def test_hybrid_path_uses_both_tools(wf, fake_llm, storage, diabetes_pdf):
    process_pdf_for_project(diabetes_pdf, "p1", user_id="u1")
    fake_llm.replies = [tool_call_message(("search_pubmed", {"query": "metformin"}),
                                          ("medical_rag_search", {"query": "metformin first line medication"})),
                        "Hybrid answer"]
    out = invoke(wf, "How does our metformin protocol compare to recent research?")
    assert sorted(o["tool"] for o in out["tool_outputs"]) == ["medical_rag_search", "search_pubmed"]


def test_double_failure_still_returns_an_answer(wf, fake_llm):
    fake_llm.replies = [RuntimeError("down"), RuntimeError("still down")]
    out = invoke(wf, "What is hypertension?", project="")
    assert out["final_answer"] and "Disclaimer" in out["final_answer"]
