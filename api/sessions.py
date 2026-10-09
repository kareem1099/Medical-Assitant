"""Stateless, signed session tokens (stored in an httpOnly cookie).

Format: ``<user_id>.<expires_unix>.<hmac>``. Nothing secret is inside the
token; the HMAC only proves the server issued it and it was not altered.
"""

import base64
import hashlib
import hmac
import secrets
import time
from typing import Optional

COOKIE_NAME = "sma_session"
SESSION_SECONDS = 7 * 24 * 3600


class SessionSigner:
    def __init__(self, secret: Optional[str] = None, lifetime: int = SESSION_SECONDS):
        self._key = (secret or secrets.token_urlsafe(32)).encode()
        self.lifetime = lifetime

    def _sign(self, payload: str) -> str:
        digest = hmac.new(self._key, payload.encode(), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).decode().rstrip("=")

    def issue(self, user_id: str, now: Optional[float] = None) -> str:
        payload = f"{user_id}.{int((time.time() if now is None else now) + self.lifetime)}"
        return f"{payload}.{self._sign(payload)}"

    def verify(self, token: Optional[str], now: Optional[float] = None) -> Optional[str]:
        """Return the user id of a valid, unexpired token - otherwise None."""
        try:
            user_id, expires, signature = (token or "").split(".")
            if not hmac.compare_digest(signature, self._sign(f"{user_id}.{expires}")):
                return None
            if int(expires) < (time.time() if now is None else now):
                return None
            return user_id or None
        except ValueError:
            return None
