"""MongoDB persistence for authenticated, user-scoped application data."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId
from pymongo import MongoClient

from config.settings import settings
from src.helpers.security import hash_password


class MongoMetadataProvider:
    """Owns MongoDB access and enforces user ownership in every operation."""

    def __init__(self, database=None):
        self._client = None
        if database is None:
            self._client = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=5000)
            self._client.admin.command("ping")
            database = self._client[settings.mongo_db_name]
        self.db = database
        self.users = self.db.users
        self.workspaces = self.db.workspaces
        self.chat_sessions = self.db.chat_sessions
        self.chat_messages = self.db.chat_messages
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        self.users.create_index("email", unique=True)
        self.workspaces.create_index([("user_id", 1), ("created_at", -1)])
        self.chat_sessions.create_index([("user_id", 1), ("updated_at", -1)])
        self.chat_messages.create_index([("user_id", 1), ("session_id", 1), ("created_at", 1)])

    @staticmethod
    def _id(value: str) -> ObjectId:
        if isinstance(value, ObjectId):
            return value
        if isinstance(value, dict):
            value = value.get("$oid") or value.get("_id") or value.get("id") or value.get("value")
        if isinstance(value, (list, tuple)):
            value = value[1] if len(value) == 2 and isinstance(value[1], str) else (value[0] if value else None)
        if not isinstance(value, str) or not ObjectId.is_valid(value):
            raise ValueError("Invalid conversation id")
        return ObjectId(value)

    def create_user(self, email: str, password: str, display_name: str) -> str:
        result = self.users.insert_one({
            "email": email.strip().lower(),
            "password_hash": hash_password(password),
            "display_name": display_name.strip(),
            "created_at": datetime.utcnow(),
            "last_login_at": None,
            "is_active": True,
            "email_verified": False,
            "codes": {},
        })
        return str(result.inserted_id)

    def create_google_user(self, email: str, google_sub: str, display_name: str) -> str:
        """Accounts from "Continue with Google": verified by Google, no password."""
        result = self.users.insert_one({
            "email": email.strip().lower(),
            "password_hash": None,
            "google_sub": google_sub,
            "display_name": display_name.strip(),
            "created_at": datetime.utcnow(),
            "last_login_at": None,
            "is_active": True,
            "email_verified": True,
            "codes": {},
        })
        return str(result.inserted_id)

    def find_user_by_google_sub(self, google_sub: str) -> Optional[Dict[str, Any]]:
        return self.users.find_one({"google_sub": google_sub, "is_active": True})

    def link_google(self, user_id: str, google_sub: str, drop_password: bool) -> None:
        """Google proved the address belongs to this person, so it counts as verified.
        ``drop_password`` discards a password nobody ever proved they own."""
        changes: Dict[str, Any] = {"google_sub": google_sub, "email_verified": True}
        if drop_password:
            changes["password_hash"] = None
        self.users.update_one({"_id": self._id(user_id)},
                              {"$set": changes, "$unset": {"codes.verify": ""}})

    def update_unverified_user(self, user_id: str, password: str, display_name: str) -> None:
        """Someone re-registers an address that was never verified: take the new details."""
        self.users.update_one({"_id": self._id(user_id), "email_verified": False}, {"$set": {
            "password_hash": hash_password(password),
            "display_name": display_name.strip(),
        }})

    def store_code(self, user_id: str, purpose: str, code_hash: str, expires_at: datetime) -> None:
        self.users.update_one({"_id": self._id(user_id)}, {"$set": {f"codes.{purpose}": {
            "hash": code_hash, "expires_at": expires_at, "sent_at": datetime.utcnow(), "attempts": 0,
        }}})

    def count_code_attempt(self, user_id: str, purpose: str) -> None:
        self.users.update_one({"_id": self._id(user_id)}, {"$inc": {f"codes.{purpose}.attempts": 1}})

    def mark_email_verified(self, user_id: str) -> None:
        self.users.update_one({"_id": self._id(user_id)},
                              {"$set": {"email_verified": True}, "$unset": {"codes.verify": ""}})

    def set_password(self, user_id: str, password: str) -> None:
        """New password; also proves the address, and ends sessions issued before now."""
        self.users.update_one({"_id": self._id(user_id)}, {
            "$set": {"password_hash": hash_password(password), "email_verified": True,
                     "password_changed_at": datetime.utcnow()},
            "$unset": {"codes.reset": "", "codes.verify": ""},
        })

    def find_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        return self.users.find_one({"email": email.strip().lower(), "is_active": True})

    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        try:
            return self.users.find_one({"_id": self._id(user_id), "is_active": True})
        except ValueError:
            return None

    def create_workspace(self, user_id: str, name: str, description: str = "") -> str:
        result = self.workspaces.insert_one({
            "user_id": user_id,
            "name": name.strip(),
            "description": description.strip(),
            "created_at": datetime.utcnow(),
        })
        return str(result.inserted_id)

    def list_workspaces(self, user_id: str) -> List[Dict[str, Any]]:
        return list(self.workspaces.find({"user_id": user_id}).sort([("created_at", -1), ("_id", -1)]))

    def create_conversation(self, user_id: str, workspace_id: Optional[str], title: str) -> str:
        now = datetime.utcnow()
        result = self.chat_sessions.insert_one({
            "user_id": user_id,
            "workspace_id": workspace_id,
            "title": title.strip() or "New conversation",
            "created_at": now,
            "updated_at": now,
            "last_message_preview": "",
            "is_archived": False,
        })
        return str(result.inserted_id)

    def list_conversations(self, user_id: str) -> List[Dict[str, Any]]:
        return list(self.chat_sessions.find({"user_id": user_id, "is_archived": False}).sort([("updated_at", -1), ("_id", -1)]))

    def get_conversation(self, user_id: str, session_id: str) -> Optional[Dict[str, Any]]:
        return self.chat_sessions.find_one({"_id": self._id(session_id), "user_id": user_id})

    def append_message(self, user_id: str, session_id: str, role: str, content: str, citations=None, source_types=None,
                       sources=None) -> str:
        if self.get_conversation(user_id, session_id) is None:
            raise PermissionError("Conversation does not belong to the authenticated user")
        now = datetime.utcnow()
        result = self.chat_messages.insert_one({
            "session_id": session_id,
            "user_id": user_id,
            "role": role,
            "content": content,
            "citations": citations or [],
            "source_types": source_types or [],
            "sources": sources or [],          # structured (type, filename/page or title/url...) for the web UI
            "created_at": now,
        })
        self.chat_sessions.update_one(
            {"_id": self._id(session_id), "user_id": user_id},
            {"$set": {"updated_at": now, "last_message_preview": content[:160]}},
        )
        return str(result.inserted_id)

    def get_messages(self, user_id: str, session_id: str) -> List[Dict[str, Any]]:
        if self.get_conversation(user_id, session_id) is None:
            raise PermissionError("Conversation does not belong to the authenticated user")
        return list(self.chat_messages.find({"user_id": user_id, "session_id": session_id}).sort("created_at", 1))

    def rename_conversation(self, user_id: str, session_id: str, title: str) -> None:
        self.chat_sessions.update_one(
            {"_id": self._id(session_id), "user_id": user_id},
            {"$set": {"title": title.strip() or "New conversation"}},
        )

    def clear_messages(self, user_id: str, session_id: str) -> None:
        """Remove every message of a conversation (the conversation itself stays)."""
        result = self.chat_sessions.update_one(
            {"_id": self._id(session_id), "user_id": user_id},
            {"$set": {"last_message_preview": ""}},
        )
        if result.matched_count:
            self.chat_messages.delete_many({"user_id": user_id, "session_id": session_id})

    def delete_workspace_conversations(self, user_id: str, workspace_id: str) -> int:
        """Delete every conversation (and its messages) of one workspace."""
        ids = [str(c["_id"]) for c in self.chat_sessions.find({"user_id": user_id, "workspace_id": workspace_id}, {"_id": 1})]
        if ids:
            self.chat_messages.delete_many({"user_id": user_id, "session_id": {"$in": ids}})
            self.chat_sessions.delete_many({"user_id": user_id, "workspace_id": workspace_id})
        return len(ids)

    def delete_conversation(self, user_id: str, session_id: str) -> None:
        result = self.chat_sessions.delete_one({"_id": self._id(session_id), "user_id": user_id})
        if result.deleted_count:
            self.chat_messages.delete_many({"user_id": user_id, "session_id": session_id})
