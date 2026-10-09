from langchain_google_genai import ChatGoogleGenerativeAI

from config.settings import Settings
from src.stores.llm.LLMInterface import LLMInterface


class GeminiProvider(LLMInterface):
    def __init__(self, settings: Settings):
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        self.settings = settings

    def get_chat_model(self):
        return ChatGoogleGenerativeAI(
            model=self.settings.llm_model,
            google_api_key=self.settings.gemini_api_key,
            temperature=self.settings.llm_temperature,
            convert_system_message_to_human=True,
        )
