"""Typed settings (pydantic-settings). Real values only via .env (never committed)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    app_log_level: str = "info"

    llm_provider: str = "openai_compatible"
    llm_base_url: str = "https://llm.example.invalid/v1"
    llm_api_key: str = ""
    llm_model: str = "demo-model"

    embedding_provider: str = "hashing"
    embedding_base_url: str = "https://llm.example.invalid/v1"
    embedding_api_key: str = ""
    embedding_model: str = "BAAI/bge-m3"
    rerank_provider: str = "none"
    rerank_base_url: str = ""
    rerank_api_key: str = ""
    rerank_model: str = "BAAI/bge-reranker-v2-m3"

    internal_api_token: str = ""
    database_url: str = "postgresql://rfq:rfq@localhost:5432/rfq"

    langfuse_enabled: bool = False
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
