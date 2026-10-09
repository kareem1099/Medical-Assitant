"""Runs the LangGraph workflow for one question and reports real progress.

Front-end independent: the web API streams the events of :func:`stream_answer`
to the browser, so the "searching PubMed / your documents" indicator reflects
what the graph is actually doing.
"""

from typing import Any, Dict, Iterator, List, Optional

from langchain_core.messages import AIMessage, HumanMessage

from src.services.citations import extract_sources

FALLBACK_ANSWER = "I could not generate an answer. Please try rephrasing your question."
PUBMED_EMAIL_NOTE = ("ℹ️ PubMed was not searched because no NCBI email is set. "
                     "Add your email in **Settings** (or `NCBI_EMAIL` in `.env`) to include recent research.")


class AnswerFailed(RuntimeError):
    """The model could not produce an answer (the turn must not be stored)."""


def _inputs(message: str, history: List[Dict[str, Any]], project_id: Optional[str]) -> Dict[str, Any]:
    messages = []
    for item in history:
        if item["role"] == "user":
            messages.append(HumanMessage(content=item["content"]))
        elif item["role"] == "assistant":
            messages.append(AIMessage(content=item["content"]))
    return {
        "messages": messages, "user_query": message, "project_id": project_id or "",
        "retrieved_docs": [], "pubmed_results": [], "tool_outputs": [], "final_answer": "",
    }


def _result(final_state: Dict[str, Any]) -> Dict[str, Any]:
    if final_state.get("failed"):
        raise AnswerFailed("The model could not generate an answer")
    answer = final_state.get("final_answer") or FALLBACK_ANSWER
    outputs = final_state.get("tool_outputs") or []
    if any(o.get("tool") == "search_pubmed" and "valid NCBI email" in o.get("content", "") for o in outputs):
        answer += f"\n\n{PUBMED_EMAIL_NOTE}"
    return {"answer": answer, "sources": extract_sources(outputs)}


def stream_answer(workflow, message: str, history: List[Dict[str, Any]], project_id: Optional[str],
                  ncbi_email: str = "", user_id: Optional[str] = None) -> Iterator[Dict[str, Any]]:
    """Yield ``{"type": "stage", ...}`` events, then one ``{"type": "result", ...}``.

    Raises :class:`AnswerFailed` when the model fails (after its own retry).
    """
    inputs = _inputs(message, history, project_id)
    config = {"configurable": {"project_id": project_id, "ncbi_email": ncbi_email, "user_id": user_id}}

    yield {"type": "stage", "stage": "thinking"}
    if not hasattr(workflow, "stream"):
        yield {"type": "result", **_result(workflow.invoke(inputs, config=config))}
        return

    final_state: Dict[str, Any] = {}
    for update in workflow.stream(inputs, config=config, stream_mode="updates"):
        for node, state in (update or {}).items():
            if node == "agent":
                calls = [c["name"] for m in state.get("messages", []) for c in (getattr(m, "tool_calls", None) or [])]
                if calls:
                    yield {"type": "stage", "stage": "searching", "tools": sorted(set(calls))}
                else:
                    yield {"type": "stage", "stage": "writing"}
            elif node == "tools":
                yield {"type": "stage", "stage": "writing"}
            elif node == "final_response":
                final_state = state
    yield {"type": "result", **_result(final_state)}
