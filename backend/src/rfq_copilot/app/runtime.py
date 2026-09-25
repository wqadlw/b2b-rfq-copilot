"""Runtime assembly: manifest → ports → RAG pipeline → graph (app is the only composition root)."""

import importlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from rfq_copilot.adapters.demo import data as demo_data
from rfq_copilot.app.freshness import CorpusFreshness, load_corpus_freshness
from rfq_copilot.app.metrics import MetricsRegistry
from rfq_copilot.app.opslog import FeedbackStore, HitStatsRegistry, NoMatchStore
from rfq_copilot.config.settings import get_settings
from rfq_copilot.core.agent.graph import GraphDeps, build_graph
from rfq_copilot.core.agent.llm import LLMClient, OpenAICompatLLM
from rfq_copilot.core.manifest import Manifest, load_manifest
from rfq_copilot.core.memory import SessionStore
from rfq_copilot.core.policies.faq_matcher import FaqMatcher, FaqRegistry
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
logger = logging.getLogger(__name__)


@dataclass
class Runtime:
    manifest: Manifest
    deps: GraphDeps
    graph: Any
    store: SessionStore
    metrics: "MetricsRegistry"
    faq_registry: FaqRegistry | None = None  # CS-faq: 运营可变 FAQ 库（app 层运营件）
    checkpointer: Any = None  # 由 init_checkpointer 按配置替换（memory 默认）
    checkpointer_conn: Any = None  # sqlite 连接句柄（shutdown 时关闭）
    # 08-knowledge-export-spec §4：离线知识模式下的语料新鲜度（demo 数据为 None）
    corpus_freshness: "CorpusFreshness | None" = None
    # 08-knowledge-export-spec §6.4：最近一轮兜底刷新结果（落 /health；未启用为 None）
    last_refresh: dict[str, Any] | None = None
    # spec 02 §3（N4）：兜底刷新历史（近 7 轮；内存态，重启清零）
    refresh_history: list[dict[str, Any]] = field(default_factory=list)
    # spec 02 §1.0：运营观测存储（RUNTIME_DATA_DIR 空 = 纯内存）
    feedback_store: FeedbackStore = field(default_factory=FeedbackStore)
    no_match_store: NoMatchStore = field(default_factory=NoMatchStore)
    hit_stats: HitStatsRegistry = field(default_factory=HitStatsRegistry)


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


def _build_rag(settings: Any, manifest: Manifest, hit_recorder: Any = None) -> RAGPipeline | None:
    """Build the pipeline with an empty store; seeding happens at app startup (async).

    QA-0007/0010：按 Settings.rag_store 装配存储——"inmemory"（demo/CI）|
    "pgvector"（prod，HNSW，DSN 缺失即 ConfigError 快速失败）。
    hit_recorder：spec 02 §2.5 命中统计钩子（仅 search() 路径触发）。
    """
    if not manifest.ports.knowledge_source.enabled:
        return None
    embedder = _build_embedder(settings)
    if settings.rag_store == "pgvector":
        from rfq_copilot.app.infra_pgvector import PgVectorStore

        store: Any = PgVectorStore(settings.rag_pgvector_dsn)
    else:
        store = InMemoryVectorStore()
    return RAGPipeline(
        embedder=embedder,
        store=store,
        reranker=NoopReranker(),
        hybrid=settings.rag_hybrid,
        hit_recorder=hit_recorder,
    )


async def seed_demo(runtime: Runtime) -> None:
    """Seed the in-memory store（demo 文档或站点离线知识集，skipped when already seeded）."""
    rag = runtime.deps.rag
    if rag is None or await rag._store.count() > 0:  # noqa: SLF001 — runtime owns its pipeline
        return
    knowledge_dir = get_settings().knowledge_data_dir
    if knowledge_dir:
        payload = json.loads((Path(knowledge_dir) / "knowledge.json").read_text(encoding="utf-8"))
        docs = [KnowledgeDocument(**d) for d in payload["documents"]]
    else:
        docs = list(demo_data.DOCS) + list(demo_data.POISON_DOCS)
    chunks = [chunk for doc in docs for chunk in chunk_document(doc)]
    await rag.ingest(chunks)
    # 08-knowledge-export-spec §4：语料保鲜——只告警不阻断
    settings = get_settings()
    if knowledge_dir:
        runtime.corpus_freshness = load_corpus_freshness(knowledge_dir, settings.rag_stale_days)
        freshness = runtime.corpus_freshness
        if freshness is not None and freshness.stale:
            logger.warning(
                "知识语料已过期：age=%.1f 天 > 阈值 %d 天（source=%s, docs=%d）——请重跑知识导出",
                freshness.age_days or 0.0,
                settings.rag_stale_days,
                freshness.source,
                freshness.doc_count,
            )


def build_runtime(adapter: str | None = None, llm: LLMClient | None = None) -> Runtime:
    """组装运行时。adapter 缺省取 ADAPTER 环境变量（默认 demo）。

    - demo：内置演示数据；若 KNOWLEDGE_DATA_DIR 非空，则目录/供应商切离线导出数据
      （站点真实产品的离线只读副本）。
    - 其他适配器（如 vacuum_b2b_sample）：由适配器自备全部端口（站点内部 API 真通道），
      不做离线数据覆盖——两条数据路径不得混用。
    """
    settings = get_settings()
    adapter = adapter or settings.adapter or "demo"  # 空 ADAPTER 环境变量回落 demo
    adapter_dir = ADAPTERS_DIR / adapter
    manifest = load_manifest(adapter_dir)  # V1~V7 validation (V2 via module import below)
    module = _adapter_module(adapter)  # V2: enabled ports must have an implementation package
    ports = module.build_demo_ports()
    if adapter == "demo" and settings.knowledge_data_dir:
        # 站点离线真实数据模式：产品目录切真实数据（KNOWLEDGE_DATA_DIR 非空时）
        from rfq_copilot.adapters.vacuum_b2b_offline.catalog import OfflineProductCatalog
        from rfq_copilot.adapters.vacuum_b2b_offline.suppliers import OfflineSupplierDirectory

        ports.catalog = OfflineProductCatalog(settings.knowledge_data_dir)
        ports.suppliers = OfflineSupplierDirectory(settings.knowledge_data_dir)
    client = llm or OpenAICompatLLM(
        base_url=settings.llm_base_url, api_key=settings.llm_api_key, model=settings.llm_model
    )
    store = SessionStore()
    # spec 02 §1.0：运营观测存储（落盘目录空串 = 纯内存，CI/测试）
    data_dir = getattr(settings, "runtime_data_dir", "") or ""
    feedback_store = FeedbackStore(data_dir)
    no_match_store = NoMatchStore(data_dir)
    hit_stats = HitStatsRegistry(data_dir)
    rag = _build_rag(settings, manifest, hit_recorder=hit_stats.record)
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
        no_match_recorder=no_match_store.append,  # spec 02 §1.2（N2）
    )
    if settings.knowledge_data_dir:
        # 行业方案/案例目录（demo 与真通道模式都注入：离线知识资产，不依赖站点在线）
        from rfq_copilot.adapters.vacuum_b2b_offline.cases import OfflineCaseDirectory
        from rfq_copilot.adapters.vacuum_b2b_offline.solutions import OfflineSolutionDirectory

        deps.solutions = OfflineSolutionDirectory(settings.knowledge_data_dir)
        deps.cases = OfflineCaseDirectory(settings.knowledge_data_dir)
    if ports.inquiry_status is not None:
        deps.inquiry_status = ports.inquiry_status
    checkpointer = MemorySaver()  # ephemeral default; init_checkpointer swaps in durable backends
    graph = build_graph(deps, checkpointer=checkpointer)
    return Runtime(
        manifest=manifest,
        deps=deps,
        graph=graph,
        store=store,
        metrics=MetricsRegistry(),
        faq_registry=FaqRegistry(build_faq()),
        checkpointer=checkpointer,
        feedback_store=feedback_store,
        no_match_store=no_match_store,
        hit_stats=hit_stats,
    )


async def init_checkpointer(runtime: Runtime, settings: Any | None = None) -> None:
    """Attach the configured checkpointer and recompile the graph (async backends need a loop).

    memory (default): the runtime already carries a MemorySaver — no-op.
    sqlite: durable single-node store; interrupt()/resume state survives a process restart.
    """
    cfg = settings or get_settings()
    backend = cfg.checkpointer_backend
    if backend == "memory":
        return
    if backend == "postgres":
        # 生产多实例模式：LangGraph 官方 AsyncPostgresSaver + 连接池（长生命周期，
        # 不走 from_conn_string 上下文管理器）。DSN 缺失大声失败——半配置不得静默降级。
        dsn = cfg.checkpointer_postgres_dsn
        if not dsn:
            raise ConfigError("checkpointer_backend=postgres requires CHECKPOINTER_POSTGRES_DSN")
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg import AsyncConnection
        from psycopg.rows import dict_row
        from psycopg_pool import AsyncConnectionPool

        pool: AsyncConnectionPool[AsyncConnection[dict[str, Any]]] = AsyncConnectionPool(
            conninfo=dsn,
            open=False,
            kwargs={"autocommit": True, "row_factory": dict_row},
        )
        await pool.open()
        pg_saver: Any = AsyncPostgresSaver(pool)
        await pg_saver.setup()
        runtime.checkpointer = pg_saver
        runtime.checkpointer_conn = pool
        runtime.graph = build_graph(runtime.deps, checkpointer=pg_saver)
        return

    if backend != "sqlite":
        raise ConfigError(f"unsupported checkpointer_backend: {backend!r} (expected memory|sqlite|postgres)")

    import aiosqlite
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    path = Path(cfg.checkpointer_sqlite_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(str(path))
    saver = AsyncSqliteSaver(conn)
    await saver.setup()
    runtime.checkpointer = saver
    runtime.checkpointer_conn = conn
    runtime.graph = build_graph(runtime.deps, checkpointer=saver)


async def close_checkpointer(runtime: Runtime) -> None:
    """Release the durable checkpointer connection (no-op for memory)."""
    conn = runtime.checkpointer_conn
    if conn is not None:
        await conn.close()  # aiosqlite Connection 与 psycopg AsyncConnectionPool 均为 awaitable close
        runtime.checkpointer_conn = None


def ui_config(runtime: Runtime) -> dict[str, Any]:
    m = runtime.manifest
    return {
        "adapter": m.adapter,
        "display_name": m.display_name,
        "chat": {
            "welcome_message": m.chat.welcome_message,
            "suggested_questions": m.chat.suggested_questions,
            "wechat": {
                "qrcode_url": m.chat.wechat.qrcode_url,
                "contact_name": m.chat.wechat.contact_name,
                "guidance_text": m.chat.wechat.guidance_text,
            },
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
