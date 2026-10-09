"""Application configuration with safe offline imports and runtime validation."""

import re
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_URI_CREDENTIALS = re.compile(r"(://[^:/@\s]+):[^@/\s]+@")


def mask_uri(uri: Optional[str]) -> str:
    """Hide the password part of ``scheme://user:password@host`` style URIs."""
    return _URI_CREDENTIALS.sub(r"\1:***@", uri or "")


class Settings(BaseSettings):
    """Type-safe configuration loaded from environment variables and .env."""

    llm_provider: str = Field(default="cohere", alias="LLM_PROVIDER")
    cohere_api_key: Optional[str] = Field(default="", alias="COHERE_API_KEY")
    gemini_api_key: Optional[str] = Field(default="", alias="GEMINI_API_KEY")
    ncbi_email: Optional[str] = Field(default="", alias="NCBI_EMAIL")
    ncbi_api_key: Optional[str] = Field(default="", alias="NCBI_API_KEY")

    embedding_model: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2", alias="EMBEDDING_MODEL"
    )
    llm_model: str = Field(default="command-a-03-2025", alias="LLM_MODEL")
    llm_temperature: float = Field(default=0.1, ge=0.0, le=2.0, alias="LLM_TEMPERATURE")
    chunk_size: int = Field(default=1000, gt=0, alias="CHUNK_SIZE")
    chunk_overlap: int = Field(default=200, ge=0, alias="CHUNK_OVERLAP")
    top_k: int = Field(default=5, gt=0, le=20, alias="TOP_K")
    score_threshold: float = Field(default=0.2, ge=0.0, le=1.0, alias="SCORE_THRESHOLD")

    mongo_uri: str = Field(default="mongodb://localhost:27017", alias="MONGO_URI")
    mongo_db_name: str = Field(default="medical_assistant", alias="MONGO_DB_NAME")
    qdrant_url: str = Field(default="http://localhost:6333", alias="QDRANT_URL")
    qdrant_api_key: Optional[str] = Field(default="", alias="QDRANT_API_KEY")
    qdrant_collection_name: str = Field(default="medical_chunks", alias="QDRANT_COLLECTION_NAME")
    qdrant_timeout: float = Field(default=30.0, gt=0, alias="QDRANT_TIMEOUT")
    log_file: str = Field(default="./logs/app.log", alias="LOG_FILE")

    # Web server. APP_SECRET signs the session cookie; when empty a random one is
    # generated at start-up (everyone is signed out whenever the server restarts).
    app_host: str = Field(default="127.0.0.1", alias="APP_HOST")
    app_port: int = Field(default=7860, gt=0, lt=65536, alias="APP_PORT")
    app_secret: Optional[str] = Field(default="", alias="APP_SECRET")
    max_upload_mb: int = Field(default=25, gt=0, alias="MAX_UPLOAD_MB")

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    @field_validator("llm_provider")
    @classmethod
    def validate_llm_provider(cls, value: str) -> str:
        provider = value.strip().lower()
        if provider not in {"cohere", "gemini"}:
            raise ValueError("LLM_PROVIDER must be either 'cohere' or 'gemini'")
        return provider

    @field_validator("ncbi_email")
    @classmethod
    def validate_email(cls, value: Optional[str]) -> str:
        if value and ("@" not in value or value.startswith("@") or value.endswith("@")):
            raise ValueError("NCBI_EMAIL must be a valid email address")
        return value or ""

    @field_validator("chunk_overlap")
    @classmethod
    def validate_chunk_overlap(cls, value: int, info) -> int:
        chunk_size = info.data.get("chunk_size", 1000)
        if value >= chunk_size:
            raise ValueError(f"CHUNK_OVERLAP ({value}) must be less than CHUNK_SIZE ({chunk_size})")
        return value

    def get_masked_config(self) -> dict:
        config = self.model_dump()
        for field in ("cohere_api_key", "gemini_api_key", "ncbi_api_key", "qdrant_api_key", "app_secret"):
            if config.get(field):
                config[field] = "***MASKED***"
        for field in ("mongo_uri", "qdrant_url"):
            config[field] = mask_uri(config.get(field))
        return config


settings = Settings()


def validate_runtime_config() -> None:
    """Validate credentials required by the configured live integrations."""
    if settings.llm_provider == "cohere" and not settings.cohere_api_key:
        raise RuntimeError("COHERE_API_KEY is required when LLM_PROVIDER=cohere")
    if settings.llm_provider == "gemini" and not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is required when LLM_PROVIDER=gemini")
