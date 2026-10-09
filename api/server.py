"""JSON API for the web front-end (``web/``) + static hosting of its build.

Every route is scoped to the signed-in user: workspaces, documents and
conversations of other users are reported as "not found".
"""

import json
import logging
import re
import shutil
import tempfile
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from api.sessions import COOKIE_NAME, SessionSigner
from config.settings import settings
from db import mongo_client
from src.controllers import AuthController, ChatController, ConversationController
from src.services.assistant import AnswerFailed, stream_answer
from src.services.documents import DocumentService, WorkspaceAccessError

logger = logging.getLogger(__name__)

DEFAULT_WORKSPACE = "My first workspace"
DEFAULT_TITLE = "New conversation"
_EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")


# --------------------------------------------------------------------- schemas
class RegisterIn(BaseModel):
    display_name: str = Field(max_length=80)
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)


class WorkspaceIn(BaseModel):
    name: str = Field(max_length=80)
    description: str = Field(default="", max_length=300)


class RenameIn(BaseModel):
    title: str = Field(max_length=120)


class MessageIn(BaseModel):
    message: str = Field(max_length=4000)
    ncbi_email: str = Field(default="", max_length=254)


# --------------------------------------------------------------------- helpers
def email_is_valid(email: Optional[str]) -> bool:
    return bool(_EMAIL.fullmatch((email or "").strip()))


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() + "Z" if isinstance(value, datetime) else None


def safe_filename(name: Optional[str]) -> str:
    """Keep the visible name (Arabic included) but no paths or control characters."""
    name = Path((name or "").replace("\\", "/")).name
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C").strip(" .")
    return name[:150] or "document.pdf"


def _message_sources(message: Dict[str, Any]) -> List[Dict[str, Any]]:
    if message.get("sources"):
        return message["sources"]
    # Messages stored before structured sources existed only kept labels.
    types = message.get("source_types") or []
    return [{"type": types[i] if i < len(types) else "local", "label": label}
            for i, label in enumerate(message.get("citations") or [])]


def _conversation(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(row["_id"]), "title": row.get("title") or DEFAULT_TITLE,
        "workspace_id": row.get("workspace_id"), "preview": row.get("last_message_preview", ""),
        "updated_at": _iso(row.get("updated_at")),
    }


def _file(row: Dict[str, Any]) -> Dict[str, Any]:
    return {**{k: row.get(k) for k in ("id", "filename", "num_pages", "num_chunks", "status", "error_message")},
            "uploaded_at": _iso(row.get("uploaded_at"))}


def _ndjson(event: Dict[str, Any]) -> bytes:
    return (json.dumps(event, ensure_ascii=False) + "\n").encode()


# ------------------------------------------------------------------------ app
def create_app(workflow, metadata, documents: Optional[DocumentService] = None,
               static_dir: Optional[Path] = None, secure_cookies: bool = False) -> FastAPI:
    app = FastAPI(title="Smart Medical Assistant", docs_url=None, redoc_url=None, openapi_url=None)
    signer = SessionSigner(settings.app_secret)
    documents = documents or DocumentService()
    auth = AuthController(metadata)
    conversations = ConversationController(metadata)
    chat = ChatController(metadata)

    # ------------------------------------------------------------- plumbing
    @app.exception_handler(Exception)
    async def unexpected(_: Request, exc: Exception):        # never leak stack traces / internals
        logger.exception("Unhandled API error: %s", exc)
        return JSONResponse({"detail": "Something went wrong. Please try again."}, status_code=500)

    def current_user(request: Request) -> Dict[str, Any]:
        user_id = signer.verify(request.cookies.get(COOKIE_NAME))
        user = metadata.get_user(user_id) if user_id else None
        if not user:
            raise HTTPException(401, "Please sign in.")
        return {"id": str(user["_id"]), "email": user["email"], "display_name": user["display_name"]}

    def start_session(response: Response, user: Dict[str, Any]) -> Dict[str, Any]:
        response.set_cookie(COOKIE_NAME, signer.issue(user["id"]), max_age=signer.lifetime,
                            httponly=True, samesite="lax", secure=secure_cookies, path="/")
        return {"user": user}

    def workspace(workspace_id: str, user: Dict[str, Any]) -> Dict[str, Any]:
        project = mongo_client.get_project(workspace_id, user_id=user["id"])
        if not project:
            raise HTTPException(404, "Workspace not found.")
        return project

    def owned_conversation(conversation_id: str, user: Dict[str, Any]) -> Dict[str, Any]:
        try:
            row = metadata.get_conversation(user["id"], conversation_id)
        except ValueError:
            row = None
        if not row:
            raise HTTPException(404, "Conversation not found.")
        return row

    # ------------------------------------------------------------------ auth
    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.post("/api/auth/register")
    def register(body: RegisterIn, response: Response):
        if not email_is_valid(body.email):
            raise HTTPException(400, "Please enter a valid email address.")
        try:
            user_id = auth.register(body.email.strip(), body.password, body.display_name)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        mongo_client.create_project(DEFAULT_WORKSPACE, "", user_id=user_id)   # ready to use right away
        return start_session(response, {"id": user_id, "email": body.email.strip().lower(),
                                        "display_name": body.display_name.strip()})

    @app.post("/api/auth/login")
    def login(body: LoginIn, response: Response):
        if not email_is_valid(body.email):
            raise HTTPException(400, "Please enter a valid email address.")
        try:
            user = auth.login(body.email, body.password)
        except PermissionError as exc:
            raise HTTPException(401, str(exc))
        return start_session(response, user)

    @app.post("/api/auth/logout")
    def logout(response: Response):
        response.delete_cookie(COOKIE_NAME, path="/")
        return {"ok": True}

    @app.get("/api/auth/me")
    def me(user=Depends(current_user)):
        return {"user": user}

    # ------------------------------------------------------------ workspaces
    @app.get("/api/workspaces")
    def list_workspaces(user=Depends(current_user)):
        return [{"id": p["id"], "name": p["name"], "description": p.get("description", ""),
                 "file_count": len(mongo_client.list_files(p["id"])), "created_at": _iso(p.get("created_at"))}
                for p in mongo_client.list_projects(user_id=user["id"])]

    @app.post("/api/workspaces", status_code=201)
    def create_workspace(body: WorkspaceIn, user=Depends(current_user)):
        if not body.name.strip():
            raise HTTPException(400, "Give the workspace a name.")
        project_id = mongo_client.create_project(body.name, body.description, user_id=user["id"])
        return {"id": project_id, "name": body.name.strip(), "description": body.description.strip(), "file_count": 0}

    @app.delete("/api/workspaces/{workspace_id}")
    def delete_workspace(workspace_id: str, user=Depends(current_user)):
        workspace(workspace_id, user)
        name = documents.delete_workspace(workspace_id, user["id"])
        metadata.delete_workspace_conversations(user["id"], workspace_id)
        return {"ok": True, "name": name}

    # ------------------------------------------------------------- documents
    @app.get("/api/workspaces/{workspace_id}/files")
    def list_files(workspace_id: str, user=Depends(current_user)):
        workspace(workspace_id, user)
        return [_file(f) for f in documents.list_files(workspace_id, user["id"])]

    @app.post("/api/workspaces/{workspace_id}/files", status_code=201)
    def upload_file(workspace_id: str, file: UploadFile = File(...), user=Depends(current_user)):
        workspace(workspace_id, user)
        name = safe_filename(file.filename)
        if not name.lower().endswith(".pdf"):
            raise HTTPException(400, "Only PDF files are supported.")
        limit = settings.max_upload_mb * 1024 * 1024
        folder = Path(tempfile.mkdtemp(prefix="sma_upload_"))
        try:
            path = folder / name
            with path.open("wb") as out:
                copied = 0
                while chunk := file.file.read(1024 * 1024):
                    copied += len(chunk)
                    if copied > limit:
                        raise HTTPException(413, f"The file is larger than {settings.max_upload_mb} MB.")
                    out.write(chunk)
            try:
                result = documents.upload(str(path), workspace_id, user["id"])
            except WorkspaceAccessError as exc:
                raise HTTPException(404, str(exc))
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        if not result.get("success"):
            raise HTTPException(422, f"Could not process {result.get('filename', name)}: {result.get('message')}")
        return {"ok": True, "filename": result["filename"], "num_chunks": result.get("num_chunks", 0),
                "replaced": bool(result.get("replaced"))}

    @app.delete("/api/workspaces/{workspace_id}/files/{file_id}")
    def delete_file(workspace_id: str, file_id: str, user=Depends(current_user)):
        try:
            return {"ok": True, "filename": documents.delete_file(file_id, workspace_id, user["id"])}
        except WorkspaceAccessError as exc:
            raise HTTPException(404, str(exc))
        except ValueError as exc:
            raise HTTPException(404, str(exc))

    # --------------------------------------------------------- conversations
    @app.get("/api/workspaces/{workspace_id}/conversations")
    def list_conversations(workspace_id: str, user=Depends(current_user)):
        workspace(workspace_id, user)
        return [_conversation(c) for c in conversations.list_for_user(user["id"], workspace_id)]

    @app.post("/api/workspaces/{workspace_id}/conversations", status_code=201)
    def new_conversation(workspace_id: str, user=Depends(current_user)):
        workspace(workspace_id, user)
        rows = conversations.list_for_user(user["id"], workspace_id)
        empty = next((c for c in rows if not c.get("last_message_preview")), None)   # reuse a blank one
        if empty:
            return _conversation(empty)
        session_id = conversations.create(user["id"], workspace_id, DEFAULT_TITLE)
        return _conversation(metadata.get_conversation(user["id"], session_id))

    @app.get("/api/conversations/{conversation_id}/messages")
    def messages(conversation_id: str, user=Depends(current_user)):
        owned_conversation(conversation_id, user)
        return [{"id": str(m["_id"]), "role": m["role"], "content": m["content"],
                 "sources": _message_sources(m), "created_at": _iso(m.get("created_at"))}
                for m in metadata.get_messages(user["id"], conversation_id)]

    @app.patch("/api/conversations/{conversation_id}")
    def rename(conversation_id: str, body: RenameIn, user=Depends(current_user)):
        owned_conversation(conversation_id, user)
        conversations.rename(user["id"], conversation_id, body.title)
        return _conversation(owned_conversation(conversation_id, user))

    @app.post("/api/conversations/{conversation_id}/clear")
    def clear(conversation_id: str, user=Depends(current_user)):
        owned_conversation(conversation_id, user)
        conversations.clear(user["id"], conversation_id)
        return {"ok": True}

    @app.delete("/api/conversations/{conversation_id}")
    def delete_conversation(conversation_id: str, user=Depends(current_user)):
        owned_conversation(conversation_id, user)
        conversations.delete(user["id"], conversation_id)
        return {"ok": True}

    # ------------------------------------------------------------------ chat
    @app.post("/api/conversations/{conversation_id}/messages")
    def ask(conversation_id: str, body: MessageIn, user=Depends(current_user)):
        """Streams NDJSON: stage events, then ``result`` (or ``error``)."""
        row = owned_conversation(conversation_id, user)
        text, ncbi_email = body.message.strip(), body.ncbi_email.strip()
        if not text:
            raise HTTPException(400, "Type a question first.")
        if ncbi_email and not email_is_valid(ncbi_email):
            raise HTTPException(400, "The NCBI email in Settings is not a valid email address.")
        project_id = row.get("workspace_id")
        if project_id:
            workspace(project_id, user)
        existing, history = chat.start_turn(user["id"], conversation_id, text)

        def events() -> Iterator[bytes]:
            try:
                for event in stream_answer(workflow, text, history, project_id, ncbi_email, user["id"]):
                    if event["type"] != "result":
                        yield _ndjson(event)
                        continue
                    chat.record_turn(user["id"], conversation_id, text, event, existing)
                    updated = metadata.get_conversation(user["id"], conversation_id) or row
                    yield _ndjson({"type": "result", "answer": event["answer"], "sources": event["sources"],
                                   "conversation": _conversation(updated)})
            except AnswerFailed:
                yield _ndjson({"type": "error", "message": "The model could not answer right now - please try again."})
            except Exception:
                logger.exception("Chat processing failed")
                yield _ndjson({"type": "error", "message": "I couldn't complete that request - please try again in a moment."})

        return StreamingResponse(events(), media_type="application/x-ndjson",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def unknown_api(rest: str):
        raise HTTPException(404, "Not found.")

    # ------------------------------------------------------- web front-end
    if static_dir and (static_dir / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")
        index = static_dir / "index.html"

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            candidate = (static_dir / path).resolve()
            if path and candidate.is_file() and static_dir.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return app
