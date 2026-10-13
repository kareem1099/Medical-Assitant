import hmac
from datetime import datetime, timedelta
from typing import Optional, Tuple

from src.controllers.BaseController import BaseController
from src.helpers.security import hash_code, hash_password, new_code, verify_password

VERIFY = "verify"
RESET = "reset"
CODE_LIFETIME = timedelta(minutes=15)
RESEND_COOLDOWN = timedelta(seconds=60)
MAX_CODE_ATTEMPTS = 5


class EmailNotVerified(PermissionError):
    """Correct password, but the address was never confirmed."""


class AuthController(BaseController):
    """Register users and authenticate them without exposing password hashes."""

    def register(self, email: str, password: str, display_name: str) -> str:
        if not email or "@" not in email:
            raise ValueError("A valid email address is required")
        if not display_name.strip():
            raise ValueError("Display name is required")
        existing = self.metadata.find_user_by_email(email)
        if existing and existing.get("email_verified"):
            raise ValueError("An account with this email already exists")
        if existing:                       # never verified: the new sign-up replaces it
            hash_password(password)        # same validation as a fresh account
            self.metadata.update_unverified_user(str(existing["_id"]), password, display_name)
            return str(existing["_id"])
        return self.metadata.create_user(email, password, display_name)

    def google_sign_in(self, profile: dict) -> dict:
        """Sign in - or sign up - with a verified Google profile (``sub``, ``email``, ``name``)."""
        user = self.metadata.find_user_by_google_sub(profile["sub"])
        if not user:
            user = self.metadata.find_user_by_email(profile["email"])
            if user:   # same address that signed up with a password earlier
                self.metadata.link_google(str(user["_id"]), profile["sub"],
                                          drop_password=not user.get("email_verified"))
            else:
                user_id = self.metadata.create_google_user(profile["email"], profile["sub"], profile["name"])
                user = self.metadata.get_user(user_id)
        self.metadata.users.update_one(
            {"_id": user["_id"]}, {"$set": {"last_login_at": datetime.utcnow()}}
        )
        return self._public(user)

    def login(self, email: str, password: str) -> dict:
        user = self.metadata.find_user_by_email(email)
        if not user or not user.get("password_hash") or not verify_password(password, user["password_hash"]):
            raise PermissionError("Invalid email or password")
        if not user.get("email_verified"):
            raise EmailNotVerified("This email was never verified. Use \"Continue with Google\" to sign in.")
        self.metadata.users.update_one(
            {"_id": user["_id"]}, {"$set": {"last_login_at": datetime.utcnow()}}
        )
        return self._public(user)

    # ------------------------------------------------------ one-time codes
    def issue_code(self, email: str, purpose: str) -> Optional[Tuple[dict, str]]:
        """New code for ``purpose`` - or None when there is nobody to send it to,
        the address is already verified, or one was sent less than a minute ago.
        Callers answer the same way in every case so accounts can't be probed."""
        user = self.metadata.find_user_by_email(email)
        if not user or (purpose == VERIFY and user.get("email_verified")):
            return None
        previous = (user.get("codes") or {}).get(purpose)
        if previous and datetime.utcnow() - previous["sent_at"] < RESEND_COOLDOWN:
            return None
        code = new_code()
        self.metadata.store_code(str(user["_id"]), purpose, hash_code(code), datetime.utcnow() + CODE_LIFETIME)
        return self._public(user), code

    def verify_email(self, email: str, code: str) -> dict:
        user = self._check_code(email, VERIFY, code)
        self.metadata.mark_email_verified(str(user["_id"]))
        return self._public(user)

    def reset_password(self, email: str, code: str, new_password: str) -> dict:
        hash_password(new_password)        # reject a weak password before spending the code
        user = self._check_code(email, RESET, code)
        self.metadata.set_password(str(user["_id"]), new_password)
        return self._public(user)

    def _check_code(self, email: str, purpose: str, code: str) -> dict:
        user = self.metadata.find_user_by_email(email)
        entry = ((user or {}).get("codes") or {}).get(purpose)
        if not entry or entry["expires_at"] < datetime.utcnow() or entry["attempts"] >= MAX_CODE_ATTEMPTS:
            raise ValueError("That code is invalid or has expired. Request a new one.")
        if not hmac.compare_digest(entry["hash"], hash_code(code or "")):
            self.metadata.count_code_attempt(str(user["_id"]), purpose)
            raise ValueError("That code is invalid or has expired. Request a new one.")
        return user

    @staticmethod
    def _public(user: dict) -> dict:
        return {"id": str(user["_id"]), "email": user["email"], "display_name": user["display_name"]}
