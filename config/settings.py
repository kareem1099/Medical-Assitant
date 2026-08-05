"""
Configuration management for the Smart Medical Assistant.

Uses Pydantic BaseSettings for type-safe configuration with
validation and .env file loading.
"""

import os
from typing import Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application configuration with validation.
    
    Loads configuration from environment variables and .env file.
    Validates required fields at startup and raises descriptive errors
    if missing.
    """
    
    # Required API Keys
    gemini_api_key: str = Field(
        ...,
        description="Google Gemini API key for LLM access",
        alias="GEMINI_API_KEY"
    )
    
    ncbi_email: str = Field(
        ...,
        description="Email address for NCBI Entrez API access",
        alias="NCBI_EMAIL"
    )
    
    # Optional API Keys
    ncbi_api_key: Optional[str] = Field(
        default="",
        description="Optional NCBI API key for higher rate limits",
        alias="NCBI_API_KEY"
    )
    
    # Model Configuration
    embedding_model: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2",
        description="HuggingFace embedding model for vector generation",
        alias="EMBEDDING_MODEL"
    )
    
    llm_model: str = Field(
        default="gemini-1.5-flash",
        description="Gemini model name for language understanding",
        alias="LLM_MODEL"
    )
    
    llm_temperature: float = Field(
        default=0.1,
        ge=0.0,
        le=2.0,
        description="LLM temperature for response generation (0.0-2.0)",
        alias="LLM_TEMPERATURE"
    )
    
    # Chunking Parameters
    chunk_size: int = Field(
        default=1000,
        gt=0,
        description="Size of text chunks for document processing",
        alias="CHUNK_SIZE"
    )
    
    chunk_overlap: int = Field(
        default=200,
        ge=0,
        description="Overlap between consecutive chunks",
        alias="CHUNK_OVERLAP"
    )
    
    # Retrieval Parameters
    top_k: int = Field(
        default=5,
        gt=0,
        le=20,
        description="Number of top results to retrieve (1-20)",
        alias="TOP_K"
    )
    
    score_threshold: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Minimum relevance score for retrieval (0.0-1.0)",
        alias="SCORE_THRESHOLD"
    )
    
    # MongoDB (stores projects, file metadata and chunk text)
    mongo_uri: str = Field(
        default="mongodb://localhost:27017",
        description="MongoDB connection URI",
        alias="MONGO_URI"
    )

    mongo_db_name: str = Field(
        default="medical_assistant",
        description="MongoDB database name",
        alias="MONGO_DB_NAME"
    )

    # Qdrant (vector database)
    qdrant_url: str = Field(
        default="http://localhost:6333",
        description="Qdrant server URL",
        alias="QDRANT_URL"
    )

    qdrant_api_key: Optional[str] = Field(
        default="",
        description="Optional Qdrant API key (for Qdrant Cloud)",
        alias="QDRANT_API_KEY"
    )

    qdrant_collection_name: str = Field(
        default="medical_chunks",
        description="Qdrant collection name used to store document chunk vectors",
        alias="QDRANT_COLLECTION_NAME"
    )

    log_file: str = Field(
        default="./logs/app.log",
        description="Path to application log file",
        alias="LOG_FILE"
    )
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    @field_validator("ncbi_email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        """Validate email format for NCBI API."""
        if not v or "@" not in v:
            raise ValueError(
                "NCBI_EMAIL must be a valid email address. "
                "Set your email in the .env file."
            )
        return v
    
    @field_validator("chunk_overlap")
    @classmethod
    def validate_chunk_overlap(cls, v: int, info) -> int:
        """Ensure chunk overlap is less than chunk size."""
        chunk_size = info.data.get("chunk_size", 1000)
        if v >= chunk_size:
            raise ValueError(
                f"CHUNK_OVERLAP ({v}) must be less than CHUNK_SIZE ({chunk_size})"
            )
        return v
    
    def get_masked_config(self) -> dict:
        """
        Get configuration dictionary with masked API keys for logging.
        
        Returns:
            Dictionary with configuration values, API keys masked
        """
        config = self.model_dump()
        
        # Mask sensitive fields
        if config.get("gemini_api_key"):
            config["gemini_api_key"] = "***MASKED***"
        if config.get("ncbi_api_key"):
            config["ncbi_api_key"] = "***MASKED***"
        if config.get("qdrant_api_key"):
            config["qdrant_api_key"] = "***MASKED***"
        
        return config


# Global settings instance
# This will raise ValidationError with descriptive messages if required fields are missing
try:
    settings = Settings()
except Exception as e:
    raise RuntimeError(
        f"Configuration error: {str(e)}\n"
        f"Please ensure all required environment variables are set in .env file.\n"
        f"See .env.example for required variables."
    ) from e
