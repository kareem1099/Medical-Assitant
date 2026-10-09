from config.settings import Settings
from src.stores.llm.LLMInterface import LLMInterface
from src.stores.llm.providers.CohereProvider import CohereProvider
from src.stores.llm.providers.GeminiProvider import GeminiProvider


class LLMProviderFactory:
    """Select the configured LLM without exposing provider SDKs to controllers."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def create(self, provider: str | None = None) -> LLMInterface:
        selected = (provider or self.settings.llm_provider).strip().lower()
        if selected == "cohere":
            return CohereProvider(self.settings)
        if selected == "gemini":
            return GeminiProvider(self.settings)
        raise ValueError(f"Unsupported LLM provider: {selected}")
