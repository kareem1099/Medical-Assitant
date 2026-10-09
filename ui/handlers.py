"""Gradio-independent UI logic.

Every public method takes plain values and returns plain values (or
``gr.update`` dicts) in the exact order of the output components declared in
``ui/gradio_app.py``. That keeps the layout file purely declarative and lets
the whole interface be tested without a browser.
"""

import logging
import re
from typing import Any, Dict, Iterator, List, Optional, Tuple

import gradio as gr
from langchain_core.messages import AIMessage, HumanMessage

from db import mongo_client
from src.controllers import AuthController, ChatController, ConversationController
from src.services.citations import extract_sources, render_sources
from src.services.documents import DocumentService, WorkspaceAccessError

logger = logging.getLogger(__name__)

SOURCES_IDLE = "Ask a question - the documents and papers used for each answer appear here."
DEFAULT_WORKSPACE = "My first workspace"
THINKING = "⏳ Searching and writing the answer…"
PUBMED_EMAIL_NOTE = ("ℹ️ PubMed was not searched because no NCBI email is set. "
                     "Add your email under **⚙️ Settings** (or `NCBI_EMAIL` in `.env`) to include recent research.")
STATUS_ICONS ={"completed": "✅", "processing": "⏳", "failed": "❌"}

_EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")


def email_is_valid(email: Optional[str]) -> bool:
    return bool(_EMAIL.fullmatch(email or ""))


def normalize_id(value: Any) -> Optional[str]:
    """Extract a Mongo id from the different shapes Gradio dropdowns can return."""
    if isinstance(value, dict):
        for key in ("id", "value", "_id", "$oid"):
            if key in value:
                return normalize_id(value[key])
        return None
    if isinstance(value, (list, tuple)):
        if len(value) == 2 and isinstance(value[1], str):
            return value[1]
        return normalize_id(value[0]) if value else None
    if value is None:
        return None
    return str(value).strip() or None


def messages_to_history(messages: List[Dict[str, Any]]) -> List[List[Optional[str]]]:
    """Stored messages -> Gradio chatbot pairs ``[user, assistant]``."""
    history: List[List[Optional[str]]] = []
    pending: Optional[str] = None
    for item in messages:
        if item["role"] == "user":
            if pending is not None:
                history.append([pending, None])
            pending = item["content"]
        else:
            history.append([pending, item["content"]])
            pending = None
    if pending is not None:
        history.append([pending, None])
    return history


def sources_from_messages(messages: List[Dict[str, Any]]) -> str:
    for item in reversed(messages):
        if item["role"] == "assistant" and item.get("citations"):
            return render_sources(item["citations"], item.get("source_types"))
    return render_sources([], [], empty=SOURCES_IDLE)


def files_markdown(files: List[Dict[str, Any]]) -> str:
    if not files:
        return "_No documents yet - upload a PDF to ground the answers in your own files._"
    rows = ["| | Document | Pages | Chunks |", "|:-:|---|--:|--:|"]
    for f in files:
        name = f["filename"].replace("|", "\\|")
        icon = STATUS_ICONS.get(f["status"], "•")
        rows.append(f"| {icon} | {name} | {f['num_pages']} | {f['num_chunks']} |")
        if f["status"] == "failed" and f.get("error_message"):
            rows.append(f"| | ↳ _{f['error_message'][:120]}_ | | |")
    return "\n".join(rows)


class AppHandlers:
    def __init__(self, metadata, workflow, documents: Optional[DocumentService] = None):
        self.metadata = metadata
        self.workflow = workflow
        self.documents = documents or DocumentService()
        self.auth = AuthController(metadata)
        self.conversations = ConversationController(metadata)
        self.chat = ChatController(metadata, workflow=self.run_workflow)

    # ------------------------------------------------------------ workflow glue
    def run_workflow(self, message, history, project_id, ncbi_email, user_id=None) -> Dict[str, Any]:
        messages = []
        for item in history:
            if item["role"] == "user":
                messages.append(HumanMessage(content=item["content"]))
            elif item["role"] == "assistant":
                messages.append(AIMessage(content=item["content"]))
        result = self.workflow.invoke(
            {
                "messages": messages, "user_query": message, "project_id": project_id or "",
                "retrieved_docs": [], "pubmed_results": [], "tool_outputs": [], "final_answer": "",
            },
            config={"configurable": {"project_id": project_id, "ncbi_email": ncbi_email, "user_id": user_id}},
        )
        if result.get("failed"):
            # Surfaces as the friendly error in send_message; nothing is saved to the conversation.
            raise RuntimeError("The model could not generate an answer")
        answer = result.get("final_answer") or "I could not generate an answer. Please try rephrasing your question."
        outputs = result.get("tool_outputs") or []
        if any(o.get("tool") == "search_pubmed" and "valid NCBI email" in o.get("content", "") for o in outputs):
            answer += f"\n\n{PUBMED_EMAIL_NOTE}"
        sources = extract_sources(outputs)
        return {
            "answer": answer,
            "citations": [s["label"] for s in sources],
            "source_types": [s["type"] for s in sources],
        }

    # ------------------------------------------------------------------ choices
    def workspace_choices(self, user_id: Optional[str]) -> List[Tuple[str, str]]:
        if not user_id:
            return []
        return [(p["name"], p["id"]) for p in mongo_client.list_projects(user_id=user_id)]

    def conversation_choices(self, user_id: Optional[str], workspace_id: Optional[str]) -> List[Tuple[str, str]]:
        if not user_id or not workspace_id:
            return []
        rows = self.conversations.list_for_user(user_id, workspace_id=workspace_id)
        return [(row.get("title") or "New conversation", str(row["_id"])) for row in rows]

    def _file_choices(self, user_id, project_id):
        files = self.documents.list_files(project_id, user_id)
        return gr.update(choices=[(f["filename"], f["id"]) for f in files], value=None)

    def _conversation_view(self, user_id, session_id):
        if not user_id or not session_id:
            return [], render_sources([], [], empty=SOURCES_IDLE)
        try:
            messages = self.metadata.get_messages(user_id, session_id)
        except (PermissionError, ValueError):
            return [], render_sources([], [], empty=SOURCES_IDLE)
        return messages_to_history(messages), sources_from_messages(messages)

    # ------------------------------------------------------------------ context
    def context(self, user_id, project_id=None, session_id=None) -> Tuple:
        """Everything that depends on (user, workspace, conversation) - one place, one order.

        Returns: project_state, project_dropdown, conversation_dropdown,
                 session_state, chatbot, sources, files_table, file_select
        """
        workspaces = self.workspace_choices(user_id)
        if project_id not in {value for _, value in workspaces}:
            project_id = workspaces[0][1] if workspaces else None

        conversations = self.conversation_choices(user_id, project_id)
        if project_id and session_id not in {value for _, value in conversations}:
            if conversations:
                session_id = conversations[0][1]
            else:
                session_id = self.conversations.create(user_id, project_id, "New conversation")
                conversations = self.conversation_choices(user_id, project_id)
        elif not project_id:
            session_id = None

        history, sources = self._conversation_view(user_id, session_id)
        return (
            project_id,
            gr.update(choices=workspaces, value=project_id),
            gr.update(choices=conversations, value=session_id),
            session_id,
            history,
            sources,
            files_markdown(self.documents.list_files(project_id, user_id)),
            self._file_choices(user_id, project_id),
        )

    def _empty_context(self) -> Tuple:
        return (
            None, gr.update(choices=[], value=None), gr.update(choices=[], value=None), None, [],
            render_sources([], [], empty=SOURCES_IDLE), files_markdown([]), gr.update(choices=[], value=None),
        )

    # --------------------------------------------------------------------- auth
    def _signed_in(self, user: Dict[str, str]) -> Tuple:
        welcome = f"👋 Signed in as **{user['display_name']}**"
        head = (user["id"], gr.update(visible=False), gr.update(visible=True), "", welcome)
        return head + self.context(user["id"])

    def _auth_failure(self, message: str) -> Tuple:
        head = (None, gr.update(visible=True), gr.update(visible=False), message, "")
        return head + self._empty_context()

    @staticmethod
    def _friendly(exc: Exception) -> str:
        if isinstance(exc, (ValueError, PermissionError)):
            return str(exc)
        logger.exception("Unexpected authentication error")
        return "Something went wrong. Please try again."

    def login(self, email: str, password: str) -> Tuple:
        try:
            if not email_is_valid(email):
                raise ValueError("Please enter a valid email address.")
            user = self.auth.login(email, password or "")
        except Exception as exc:
            return self._auth_failure(f"❌ {self._friendly(exc)}")
        return self._signed_in(user)

    def register(self, display_name: str, email: str, password: str) -> Tuple:
        try:
            if not email_is_valid(email):
                raise ValueError("Please enter a valid email address.")
            user_id = self.auth.register(email, password or "", display_name or "")
            # Every account starts with a ready-to-use workspace.
            mongo_client.create_project(DEFAULT_WORKSPACE, "", user_id=user_id)
            user = {"id": user_id, "email": email.strip().lower(), "display_name": display_name.strip()}
        except Exception as exc:
            return self._auth_failure(f"❌ {self._friendly(exc)}")
        return self._signed_in(user)

    def logout(self) -> Tuple:
        return self._auth_failure("You have been signed out.")

    # ---------------------------------------------------------------- workspaces
    def select_workspace(self, project_id, user_id) -> Tuple:
        return self.context(user_id, normalize_id(project_id))

    def create_workspace(self, name: str, description: str, user_id: str) -> Tuple:
        """Returns: status, name_box, description_box, *context"""
        if not user_id:
            return ("❌ Please sign in first.", name, description) + self._empty_context()
        if not name or not name.strip():
            return ("❌ Give the workspace a name.", name, description) + self.context(user_id)
        try:
            project_id = mongo_client.create_project(name, description or "", user_id=user_id)
        except Exception as exc:
            return (f"❌ {self._friendly(exc)}", name, description) + self.context(user_id)
        return (f"✅ Created **{name.strip()}**", "", "") + self.context(user_id, project_id)

    def delete_workspace(self, project_id, user_id, confirmed: bool) -> Tuple:
        """Returns: status, confirm_checkbox, *context"""
        project_id = normalize_id(project_id)
        if not confirmed:
            return ("Tick the box to confirm - this cannot be undone.", False) + self.context(user_id, project_id)
        try:
            name = self.documents.delete_workspace(project_id, user_id)
            self.metadata.delete_workspace_conversations(user_id, project_id)
        except (WorkspaceAccessError, ValueError) as exc:
            return (f"❌ {exc}", False) + self.context(user_id, project_id)
        return (f"🗑️ Deleted workspace **{name}** with its documents and conversations.", False) + self.context(user_id)

    # ---------------------------------------------------------------- documents
    def upload_pdf(self, pdf_file, project_id, user_id) -> Tuple:
        """Returns: status, files_table, file_select, upload_box"""
        project_id = normalize_id(project_id)

        def done(status):
            return (status, files_markdown(self.documents.list_files(project_id, user_id)),
                    self._file_choices(user_id, project_id), None)

        if not user_id:
            return done("❌ Please sign in first.")
        if not project_id:
            return done("❌ Select or create a workspace first.")
        if pdf_file is None:
            return done("❌ Choose a PDF file first.")
        try:
            result = self.documents.upload(pdf_file, project_id, user_id)
        except WorkspaceAccessError as exc:
            return done(f"❌ {exc}")
        except Exception:
            logger.exception("PDF upload failed")
            return done("❌ Unexpected error while processing the file. See the logs for details.")
        if not result["success"]:
            return done(f"❌ Could not process **{result['filename']}** - {result['message']}")
        extra = " (replaced the previous copy)" if result.get("replaced") else ""
        return done(f"✅ **{result['filename']}** added{extra} - {result['num_chunks']} searchable chunks.")

    def delete_file(self, file_id, project_id, user_id) -> Tuple:
        """Returns: status, files_table, file_select"""
        project_id, file_id = normalize_id(project_id), normalize_id(file_id)
        try:
            if not file_id:
                raise ValueError("Pick the document to remove first.")
            name = self.documents.delete_file(file_id, project_id, user_id)
            status = f"🗑️ Removed **{name}**."
        except (WorkspaceAccessError, ValueError) as exc:
            status = f"❌ {exc}"
        return (status, files_markdown(self.documents.list_files(project_id, user_id)),
                self._file_choices(user_id, project_id))

    # ------------------------------------------------------------ conversations
    def new_conversation(self, user_id, project_id) -> Tuple:
        """Returns: conversation_dropdown, session_state, chatbot, sources"""
        project_id = normalize_id(project_id)
        if not user_id or not project_id:
            return gr.update(), None, [], render_sources([], [], empty="Select a workspace first.")
        # Re-use an untouched empty conversation instead of piling up blank ones.
        session_id = next(
            (str(c["_id"]) for c in self.conversations.list_for_user(user_id, project_id)
             if not c.get("last_message_preview")), None)
        if not session_id:
            session_id = self.conversations.create(user_id, project_id, "New conversation")
        return (gr.update(choices=self.conversation_choices(user_id, project_id), value=session_id),
                session_id, [], render_sources([], [], empty=SOURCES_IDLE))

    def load_conversation(self, user_id, session_id) -> Tuple:
        """Returns: session_state, chatbot, sources"""
        session_id = normalize_id(session_id)
        history, sources = self._conversation_view(user_id, session_id)
        return session_id, history, sources

    def delete_conversation(self, user_id, session_id, project_id) -> Tuple:
        """Returns: conversation_dropdown, session_state, chatbot, sources"""
        session_id = normalize_id(session_id)
        if user_id and session_id:
            try:
                self.conversations.delete(user_id, session_id)
            except ValueError:
                pass
        project_id = normalize_id(project_id)
        remaining = self.conversation_choices(user_id, project_id)
        if remaining:
            sid = remaining[0][1]
            history, sources = self._conversation_view(user_id, sid)
            return gr.update(choices=remaining, value=sid), sid, history, sources
        return self.new_conversation(user_id, project_id)

    def clear_conversation(self, user_id, session_id) -> Tuple:
        """Returns: chatbot, sources"""
        session_id = normalize_id(session_id)
        if user_id and session_id:
            try:
                self.conversations.clear(user_id, session_id)
            except ValueError:
                pass
        return [], render_sources([], [], empty=SOURCES_IDLE)

    # --------------------------------------------------------------------- chat
    def send_message(self, message, history, project_id, ncbi_email, user_id, session_id) -> Iterator[Tuple]:
        """Generator. Yields: msg_box, chatbot, sources, session_state, conversation_dropdown"""
        history = [list(pair) for pair in (history or [])]
        project_id, session_id = normalize_id(project_id), normalize_id(session_id)
        text = (message or "").strip()
        ncbi_email = (ncbi_email or "").strip()      # pasted emails often carry stray spaces
        keep = gr.update()

        if not text:
            yield message, history, keep, session_id, keep
            return

        def notice(msg, side=""):
            return history + [[text, msg]], side or render_sources([], [], empty=SOURCES_IDLE)

        if not user_id:
            chat, side = notice("❌ Please sign in first.")
            yield text, chat, side, session_id, keep
            return
        if not project_id or not session_id:
            chat, side = notice("❌ Create or select a workspace before asking a question.")
            yield text, chat, side, session_id, keep
            return
        if ncbi_email and not email_is_valid(ncbi_email):
            chat, side = notice("❌ The NCBI email in Settings is not a valid email address.")
            yield text, chat, side, session_id, keep
            return

        history.append([text, THINKING])
        yield "", [list(pair) for pair in history], keep, session_id, keep   # show the question at once, clear the box
        try:
            result = self.chat.send_message(user_id, session_id, text, project_id, ncbi_email)
        except PermissionError:
            history[-1][1] = "❌ That conversation is not available. Start a new one."
            yield "", history, keep, session_id, keep
            return
        except Exception:
            logger.exception("Chat processing failed")
            history[-1][1] = ("⚠️ I couldn't complete that request - please try again in a moment. "
                              "(Technical details were written to the log.)")
            yield "", history, keep, session_id, keep
            return
        history[-1][1] = result["answer"]
        sources = render_sources(result["citations"], result["source_types"], empty="No documents or papers were needed for this answer.")
        yield ("", history, sources, session_id,
               gr.update(choices=self.conversation_choices(user_id, project_id), value=session_id))
