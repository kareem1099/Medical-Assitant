from abc import ABC, abstractmethod


class LLMInterface(ABC):
    """Provider-neutral chat model contract."""

    @abstractmethod
    def get_chat_model(self):
        """Return a configured LangChain-compatible chat model."""
