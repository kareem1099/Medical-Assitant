from langchain_cohere import ChatCohere

from config.settings import Settings
from src.stores.llm.LLMInterface import LLMInterface


class CohereProvider(LLMInterface):
    def __init__(self, settings: Settings):
        if not settings.cohere_api_key:
            raise RuntimeError("COHERE_API_KEY is not configured")
        self.settings = settings

    def get_chat_model(self):
        return ChatCohere(
            model=self.settings.llm_model,
            cohere_api_key=self.settings.cohere_api_key,
            temperature=self.settings.llm_temperature,
        )
