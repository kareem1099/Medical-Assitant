"""Verifies the ID token that Google Identity Services hands the browser."""

from typing import Dict

from google.auth.exceptions import GoogleAuthError
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from config.settings import settings

_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}


class GoogleVerifier:
    def __init__(self):
        self._transport = google_requests.Request()   # caches Google's signing keys

    def verify(self, credential: str) -> Dict[str, str]:
        """``{sub, email, name}`` of a valid token for our client - otherwise ValueError."""
        if not settings.google_client_id:
            raise ValueError("Google sign-in is not configured on this server.")
        try:
            claims = id_token.verify_oauth2_token(credential, self._transport, settings.google_client_id)
        except GoogleAuthError as exc:          # e.g. Google's keys could not be fetched
            raise ValueError(str(exc)) from exc
        if claims.get("iss") not in _ISSUERS:
            raise ValueError("Invalid Google token issuer.")
        if not claims.get("email") or not claims.get("email_verified"):
            raise ValueError("Your Google account has no verified email address.")
        return {"sub": claims["sub"], "email": claims["email"],
                "name": claims.get("name") or claims["email"].split("@")[0]}
