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

    # spec 02-engine-read-api-spec §1.0：运营观测数据（feedback/no_match/hit_stats）落盘目录；
    # 缺省空串 = 纯内存（CI/测试零意外写盘）；生产 .env 显式设 runtime_data 开启持久化。
    runtime_data_dir: str = ""

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

    # QA-0007/0010：RAG 向量存储装配——"inmemory"（demo/CI）| "pgvector"（prod，HNSW）
    rag_store: str = "inmemory"
    rag_pgvector_dsn: str = ""  # rag_store=pgvector 时必填

    # 08-knowledge-export-spec §4：知识语料保鲜阈值（天）——corpus age 超过即 stale 告警
    rag_stale_days: int = 14

    # 08-knowledge-export-spec §6：引擎内置每日兜底刷新（webhook 防丢失的定时兜底）
    knowledge_refresh_enabled: bool = False  # 显式 opt-in；测试/CI 不启用
    knowledge_source_dir: str = ""  # 站点 database/seeders 目录；缺失则调度器禁用并 WARN
    knowledge_refresh_interval_hours: int = 24  # 启动 60s 宽限首跑，此后按间隔循环

    # 01-port-spec §6.4：混合检索（向量+关键词 RRF）——false 回落纯向量单路
    rag_hybrid: bool = True

    langfuse_enabled: bool = False
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
