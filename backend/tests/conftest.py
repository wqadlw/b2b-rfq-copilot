"""Shared fixtures: demo manifest + GraphDeps with FakeLLM + in-memory ports."""

from pathlib import Path
from typing import Any

import pytest

from rfq_copilot.adapters.demo import data as demo_data
from rfq_copilot.adapters.demo.adapter import build_demo_ports
from rfq_copilot.core.agent.graph import GraphDeps
from rfq_copilot.core.agent.llm import FakeLLM
from rfq_copilot.core.manifest import Manifest, load_manifest
from rfq_copilot.core.memory import SessionStore
from rfq_copilot.core.policies.refusal import derive_refusal_policies
from rfq_copilot.core.prompts import PromptRegistry
from rfq_copilot.core.rag.chunking import chunk_document
from rfq_copilot.core.rag.embedding import HashingEmbedder
from rfq_copilot.core.rag.pipeline import RAGPipeline
from rfq_copilot.core.rag.reranker import NoopReranker
from rfq_copilot.core.rag.store import InMemoryVectorStore

ADAPTER_DIR = Path(__file__).resolve().parents[1] / "src" / "rfq_copilot" / "adapters" / "demo"


@pytest.fixture()
def demo_manifest() -> Manifest:
    return load_manifest(ADAPTER_DIR)


def make_deps(scripted: list[dict[str, Any]] | None = None, manifest: Manifest | None = None) -> tuple[GraphDeps, Any]:
    ports = build_demo_ports()
    m = manifest or load_manifest(ADAPTER_DIR)
    # seed the M1 RAG store synchronously (hashing embeddings; deterministic in CI)
    store = InMemoryVectorStore()
    docs = list(demo_data.DOCS) + list(demo_data.POISON_DOCS)
    chunks = [chunk for doc in docs for chunk in chunk_document(doc)]
    # 协议转 async 后（QA-0007/0010），同步测试装配直接填 rows（make_deps 会在事件循环内被调用）
    store.rows.extend(zip(chunks, HashingEmbedder().embed_sync([c.content for c in chunks]), strict=True))
    rag = RAGPipeline(embedder=HashingEmbedder(), store=store, reranker=NoopReranker())
    deps = GraphDeps(
        manifest=m,
        llm=FakeLLM(scripted or []),
        prompts=PromptRegistry(),
        refusal_policies=derive_refusal_policies(m),
        store=SessionStore(),
        catalog=ports.catalog,
        suppliers=ports.suppliers,
        rag=rag,
        inquiry_sink=ports.inquiry_sink,
        lead_distribution=ports.lead_distribution,
    )
    return deps, ports


def understanding(intent: str, route: str, confidence: float = 0.9, **extra: Any) -> dict[str, Any]:
    return {
        "intent": intent,
        "confidence": confidence,
        "entities": {},
        "missing_fields": [],
        "route": route,
        "needs_clarification": False,
        "needs_human": False,
        "human_reason": None,
        "refusal_reason": None,
        **extra,
    }


# ===== QA-0021：测试 hermetic（与宿主 .env / 进程环境解耦）=====
# pydantic-settings 会读 CWD 下 .env 与进程环境变量；仓库根的 .env 指向真实站点，
# 污染 pytest（脏 env 13F/270P）。此 autouse fixture 统一屏蔽并清 get_settings 缓存，
# 保证净/脏环境跑 pytest 结果一致。
_NEUTRAL_ENV_KEYS = [
    "ADAPTER",
    "AI_TICKET_SECRET",
    "INTERNAL_API_TOKEN",
    "INTERNAL_API_BASE_URL",
    "KNOWLEDGE_DATA_DIR",
    "CHECKPOINTER_BACKEND",
    "CHECKPOINTER_SQLITE_PATH",
    "CHECKPOINTER_POSTGRES_DSN",
    "APP_ENV",
    "APP_LOG_LEVEL",
    "LLM_PROVIDER",
    "LLM_BASE_URL",
    "LLM_API_KEY",
    "LLM_MODEL",
    "LLM_DAILY_TOKEN_BUDGET",
    "GUEST_TIER_ENABLED",
    "EMBEDDING_PROVIDER",
    "EMBEDDING_BASE_URL",
    "EMBEDDING_API_KEY",
    "EMBEDDING_MODEL",
    "RERANK_PROVIDER",
    "RERANK_BASE_URL",
    "RERANK_API_KEY",
    "RERANK_MODEL",
    "DATABASE_URL",
    "LANGFUSE_ENABLED",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
]


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch):
    from rfq_copilot.config.settings import Settings, get_settings

    # 禁用 .env 文件加载（Settings(env_file=".env") 以 CWD 相对读取）
    monkeypatch.setattr(
        Settings,
        "model_config",
        {**Settings.model_config, "env_file": None},
    )
    for key in _NEUTRAL_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
