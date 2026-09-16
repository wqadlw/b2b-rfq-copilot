"""Runtime assembly: manifest → ports → RAG pipeline → graph (app is the only composition root)."""

import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from rfq_copilot.adapters.demo import data as demo_data
from rfq_copilot.app.metrics import MetricsRegistry
from rfq_copilot.config.settings import get_settings
from rfq_copilot.core.agent.graph import GraphDeps, build_graph
from rfq_copilot.core.agent.llm import LLMClient, OpenAICompatLLM
from rfq_copilot.core.manifest import Manifest, load_manifest
from rfq_copilot.core.memory import SessionStore
from rfq_copilot.core.policies.faq_matcher import FaqMatcher
from rfq_copilot.core.policies.faq_matcher import build_default_faq as build_faq
from rfq_copilot.core.policies.refusal import derive_refusal_policies
from rfq_copilot.core.prompts import PromptRegistry
from rfq_copilot.core.rag.chunking import chunk_document
from rfq_copilot.core.rag.embedding import HashingEmbedder, OpenAICompatEmbedder
from rfq_copilot.core.rag.pipeline import RAGPipeline
from rfq_copilot.core.rag.reranker import NoopReranker
from rfq_copilot.core.rag.store import InMemoryVectorStore
from rfq_copilot.ports.errors import ConfigError
from rfq_copilot.ports.knowledge_source import KnowledgeDocument

ADAPTERS_DIR = Path(__file__).resolve().parent.parent / "adapters"
POISONED_IDS = frozenset({"demo-kb-poison-001", "demo-kb-poison-002", "demo-kb-poison-003"})


@dataclass
class Runtime:
    manifest: Manifest
    deps: GraphDeps
    graph: Any
    store: SessionStore
    metrics: "MetricsRegistry"


def _adapter_module(adapter: str) -> Any:
    try:
        return importlib.import_module(f"rfq_copilot.adapters.{adapter}.adapter")
    except ImportError as exc:
        raise ConfigError(f"adapter implementation not found: {adapter}") from exc


def _build_embedder(settings: Any) -> HashingEmbedder | OpenAICompatEmbedder:
    if settings.embedding_provider == "openai_compatible":
        return OpenAICompatEmbedder(
            base_url=settings.embedding_base_url,
            api_key=settings.embedding_api_key,
            model=settings.embedding_model,
        )
    return HashingEmbedder()


def _build_rag(settings: Any, manifest: Manifest) -> RAGPipeline | None:
    """Build the pipeline with an empty store; seeding happens at app startup (async)."""
    if not manifest.ports.knowledge_source.enabled:
        return None
    embedder = _build_embedder(settings)
    return RAGPipeline(embedder=embedder, store=InMemoryVectorStore(), reranker=NoopReranker())


async def seed_demo(runtime: Runtime) -> None:
    """Seed the in-memory store（demo 文档或 ZZK 真实知识集，skipped when already seeded）."""
    rag = runtime.deps.rag
    if rag is None or rag._store.count() > 0:  # noqa: SLF001 — runtime owns its pipeline
        return
    zzk_dir = get_settings().knowledge_data_dir
    if zzk_dir:
        payload = json.loads((Path(zzk_dir) / "zzk_knowledge.json").read_text(encoding="utf-8"))
        docs = [KnowledgeDocument(**d) for d in payload["documents"]]
    else:
        docs = list(demo_data.DOCS) + list(demo_data.POISON_DOCS)
    chunks = [chunk for doc in docs for chunk in chunk_document(doc)]
    await rag.ingest(chunks)


def build_runtime(adapter: str = "demo", llm: LLMClient | None = None) -> Runtime:
    adapter_dir = ADAPTERS_DIR / adapter
    manifest = load_manifest(adapter_dir)  # V1~V7 validation (V2 via module import below)
    module = _adapter_module(adapter)  # V2: enabled ports must have an implementation package
    ports = module.build_demo_ports()
    # ZZK 真实数据模式：产品目录切真实数据（KNOWLEDGE_DATA_DIR 非空时）
    from rfq_copilot.adapters.zhaozhenkong_offline.zzk_catalog import ZzkProductCatalog

    if get_settings().knowledge_data_dir:
        from rfq_copilot.adapters.zhaozhenkong_offline.zzk_suppliers import ZzkSupplierDirectory

        ports.catalog = ZzkProductCatalog(get_settings().knowledge_data_dir)
        ports.suppliers = ZzkSupplierDirectory(get_settings().knowledge_data_dir)
    settings = get_settings()
    client = llm or OpenAICompatLLM(
        base_url=settings.llm_base_url, api_key=settings.llm_api_key, model=settings.llm_model
    )
    store = SessionStore()
    rag = _build_rag(settings, manifest)
    deps = GraphDeps(
        manifest=manifest,
        llm=client,
        prompts=PromptRegistry(),
        refusal_policies=derive_refusal_policies(manifest),
        store=store,
        faq_matcher=FaqMatcher(build_faq()),
        catalog=ports.catalog if manifest.ports.product_catalog.enabled else None,
        suppliers=ports.suppliers if manifest.ports.supplier_directory.enabled else None,
        rag=rag,
        inquiry_sink=ports.inquiry_sink if manifest.ports.inquiry_sink.enabled else None,
        lead_distribution=ports.lead_distribution if manifest.ports.lead_distribution.enabled else None,
        poisoned_ids=POISONED_IDS,
    )
    graph = build_graph(deps, checkpointer=MemorySaver())  # demo profile; prod swaps AsyncPostgresSaver
    return Runtime(manifest=manifest, deps=deps, graph=graph, store=store, metrics=MetricsRegistry())


def ui_config(runtime: Runtime) -> dict[str, Any]:
    m = runtime.manifest
    return {
        "adapter": m.adapter,
        "display_name": m.display_name,
        "chat": {
            "welcome_message": m.chat.welcome_message,
            "suggested_questions": m.chat.suggested_questions,
        },
        "theme": {"primary": m.chat.theme_primary},
        "capabilities": {
            "product_catalog": m.ports.product_catalog.enabled,
            "supplier_directory": m.ports.supplier_directory.enabled,
            "knowledge_source": m.ports.knowledge_source.enabled,
            "inquiry": m.ports.inquiry_sink.enabled,
            "lead_distribution": m.ports.lead_distribution.enabled,
            "pricing": m.capabilities.pricing.enabled,
            "lead_time": m.capabilities.lead_time.enabled,
            "stock": m.capabilities.stock.enabled,
        },
        "inquiry": {
            "guest_allowed": m.ports.inquiry_sink.guest_allowed,
            "required_fields": m.ports.inquiry_sink.required_fields,
        },
        "i18n": "zh-CN",
    }
