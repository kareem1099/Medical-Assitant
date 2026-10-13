import pytest
from google.auth.exceptions import TransportError

from config.settings import settings
from src.services import google_auth
from src.services.google_auth import GoogleVerifier

CLAIMS = {"iss": "https://accounts.google.com", "sub": "123", "email": "k@x.co", "email_verified": True, "name": "Kareem"}


@pytest.fixture
def verifier(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "client-1")
    return GoogleVerifier()


def fake_tokens(monkeypatch, result):
    def verify(credential, transport, audience):
        assert audience == "client-1"
        if isinstance(result, Exception):
            raise result
        return result
    monkeypatch.setattr(google_auth.id_token, "verify_oauth2_token", verify)


def test_valid_token_gives_the_profile(verifier, monkeypatch):
    fake_tokens(monkeypatch, CLAIMS)
    assert verifier.verify("t") == {"sub": "123", "email": "k@x.co", "name": "Kareem"}


def test_name_falls_back_to_the_email(verifier, monkeypatch):
    fake_tokens(monkeypatch, {**CLAIMS, "name": ""})
    assert verifier.verify("t")["name"] == "k"


@pytest.mark.parametrize("claims", [
    {**CLAIMS, "iss": "evil.example"},
    {**CLAIMS, "email_verified": False},
    {**CLAIMS, "email": ""},
])
def test_untrusted_claims_are_rejected(verifier, monkeypatch, claims):
    fake_tokens(monkeypatch, claims)
    with pytest.raises(ValueError):
        verifier.verify("t")


@pytest.mark.parametrize("error", [ValueError("bad signature"), TransportError("offline")])
def test_invalid_or_unverifiable_tokens_raise_value_error(verifier, monkeypatch, error):
    fake_tokens(monkeypatch, error)
    with pytest.raises(ValueError):
        verifier.verify("t")


def test_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "")
    with pytest.raises(ValueError, match="not configured"):
        GoogleVerifier().verify("t")


def test_real_check_rejects_garbage(verifier):
    with pytest.raises(ValueError):
        verifier.verify("not-a-jwt")
