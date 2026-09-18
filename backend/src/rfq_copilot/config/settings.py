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

    # 适配器选择：demo（内置演示数据/离线导出数据）| vacuum_b2b_sample（站点内部 API 真通道）
    adapter: str = "demo"
    internal_api_base_url: str = ""  # 宿主站点内部 API 基址（如 http://127.0.0.1:8001）
    internal_api_token: str = ""

    # CS-tiered access: per-user daily LLM completion-token budget (cost guardrail).
    llm_daily_token_budget: int = 20000
    # Guest tier gate: when true, guests (no user_ref) are limited to 0-token paths and
    # LLM turns return login_required. Demo/tests default false (open chat).
    guest_tier_enabled: bool = False
    database_url: str = "postgresql://rfq:rfq@localhost:5432/rfq"

    knowledge_data_dir: str = ""

    # Graph checkpointer backend: "memory" (ephemeral; tests/demo), "sqlite" (durable
    # single-node: interrupt()/resume state survives a restart; M1+ default candidate).
    checkpointer_backend: str = "memory"
    checkpointer_sqlite_path: str = ".data/checkpoints.sqlite"
    checkpointer_postgres_dsn: str = ""
    ai_ticket_secret: str = ""  # E1 鉴权桥：与宿主站点 .env 的 AI_TICKET_SECRET 同值；空=不验签（向后兼容）
    # QA-0001 / ADR-0005：CORS 显式白名单（逗号分隔，如
    # https://your-domain.com,https://www.your-domain.com）；空=仅本机开发源放行
    cors_allow_origins: str = ""
    # postgresql://user:***@host:5432/db（postgres 后端必填）

    langfuse_enabled: bool = False
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
