import pytest
from pydantic import ValidationError

from config.settings import Settings, settings, validate_runtime_config


def make(**env):
    return Settings(_env_file=None, **env)


def test_defaults_are_sane():
    s = make()
    assert s.llm_provider == "cohere"
    assert s.chunk_overlap < s.chunk_size
    assert 0 < s.top_k <= 20
    assert 0.0 <= s.score_threshold <= 1.0
    assert s.qdrant_collection_name


@pytest.mark.parametrize("value", ["cohere", "COHERE", " Gemini "])
def test_provider_is_normalised(value):
    assert make(LLM_PROVIDER=value).llm_provider == value.strip().lower()


def test_unknown_provider_rejected():
    with pytest.raises(ValidationError):
        make(LLM_PROVIDER="openai")


@pytest.mark.parametrize("email", ["nope", "@x.com", "x@"])
def test_bad_ncbi_email_rejected(email):
    with pytest.raises(ValidationError):
        make(NCBI_EMAIL=email)


def test_empty_ncbi_email_allowed():
    assert make(NCBI_EMAIL="").ncbi_email == ""


def test_overlap_must_be_smaller_than_chunk_size():
    with pytest.raises(ValidationError):
        make(CHUNK_SIZE=100, CHUNK_OVERLAP=100)
    assert make(CHUNK_SIZE=100, CHUNK_OVERLAP=99).chunk_overlap == 99


@pytest.mark.parametrize("name,value", [("TOP_K", 0), ("TOP_K", 21), ("SCORE_THRESHOLD", 1.5),
                                         ("LLM_TEMPERATURE", 3), ("CHUNK_SIZE", 0)])
def test_numeric_bounds(name, value):
    with pytest.raises(ValidationError):
        make(**{name: value})


def test_masked_config_hides_every_secret():
    s = make(COHERE_API_KEY="secret-1", GEMINI_API_KEY="secret-2",
             NCBI_API_KEY="secret-3", QDRANT_API_KEY="secret-4")
    dumped = str(s.get_masked_config())
    for secret in ("secret-1", "secret-2", "secret-3", "secret-4"):
        assert secret not in dumped
    assert "***MASKED***" in dumped


def test_masked_config_hides_credentials_inside_mongo_uri():
    s = make(MONGO_URI="mongodb+srv://admin:SuperSecret@cluster0.example.net/db")
    assert "SuperSecret" not in str(s.get_masked_config())


def test_runtime_validation_requires_key_of_selected_provider(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "cohere")
    monkeypatch.setattr(settings, "cohere_api_key", "")
    with pytest.raises(RuntimeError, match="COHERE_API_KEY"):
        validate_runtime_config()

    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(settings, "gemini_api_key", "")
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        validate_runtime_config()

    monkeypatch.setattr(settings, "gemini_api_key", "k")
    validate_runtime_config()  # no error
