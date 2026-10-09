import pytest

from config.settings import Settings
from src.stores.llm import LLMProviderFactory
from src.stores.llm.providers import CohereProvider, GeminiProvider


def s(**kw):
    return Settings(_env_file=None, **kw)


def test_factory_selects_provider_from_settings():
    assert isinstance(LLMProviderFactory(s(COHERE_API_KEY="k")).create(), CohereProvider)
    assert isinstance(LLMProviderFactory(s(LLM_PROVIDER="gemini", GEMINI_API_KEY="k")).create(), GeminiProvider)


def test_explicit_provider_overrides_settings():
    f = LLMProviderFactory(s(COHERE_API_KEY="k", GEMINI_API_KEY="g"))
    assert isinstance(f.create("GEMINI"), GeminiProvider)


def test_unknown_provider():
    with pytest.raises(ValueError, match="Unsupported"):
        LLMProviderFactory(s()).create("openai")


@pytest.mark.parametrize("cls,kw,msg", [(CohereProvider, {}, "COHERE_API_KEY"), (GeminiProvider, {}, "GEMINI_API_KEY")])
def test_missing_keys_fail_fast(cls, kw, msg):
    with pytest.raises(RuntimeError, match=msg):
        cls(s(COHERE_API_KEY="", GEMINI_API_KEY=""))


def test_chat_models_are_configured_from_settings():
    cohere = CohereProvider(s(COHERE_API_KEY="k", LLM_MODEL="command-a-03-2025", LLM_TEMPERATURE=0.3)).get_chat_model()
    assert cohere.model == "command-a-03-2025" and cohere.temperature == 0.3
    gemini = GeminiProvider(s(LLM_PROVIDER="gemini", GEMINI_API_KEY="k", LLM_MODEL="gemini-1.5-flash")).get_chat_model()
    assert "gemini-1.5-flash" in gemini.model


def test_graph_get_llm_uses_the_selected_provider(monkeypatch, test_settings):
    import graph.nodes as nodes

    assert type(nodes.get_llm()).__name__ == "ChatCohere"
    monkeypatch.setattr(test_settings, "cohere_api_key", "")
    with pytest.raises(RuntimeError, match="COHERE_API_KEY"):
        nodes.get_llm()
    monkeypatch.setattr(test_settings, "llm_provider", "gemini")
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        nodes.get_llm()
