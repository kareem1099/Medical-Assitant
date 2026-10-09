from datetime import datetime

from src.controllers.BaseController import BaseController
from src.helpers.security import verify_password


class AuthController(BaseController):
    """Register users and authenticate them without exposing password hashes."""

    def register(self, email: str, password: str, display_name: str) -> str:
        if not email or "@" not in email:
            raise ValueError("A valid email address is required")
        if not display_name.strip():
            raise ValueError("Display name is required")
        if self.metadata.find_user_by_email(email):
            raise ValueError("An account with this email already exists")
        return self.metadata.create_user(email, password, display_name)

    def login(self, email: str, password: str) -> dict:
        user = self.metadata.find_user_by_email(email)
        if not user or not verify_password(password, user["password_hash"]):
            raise PermissionError("Invalid email or password")
        self.metadata.users.update_one(
            {"_id": user["_id"]}, {"$set": {"last_login_at": datetime.utcnow()}}
        )
        return {"id": str(user["_id"]), "email": user["email"], "display_name": user["display_name"]}
