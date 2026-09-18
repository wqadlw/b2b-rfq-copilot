"""QA-0007/0010 回归：VectorStore 协议异步统一 + build_runtime 按 Settings 装配。

- QA-0007：PgVectorStore 满足 VectorStore 协议（async add/search/remove_by_doc_id/count），
  用 Fake asyncpg 连接验证 SQL 分支与 ScoredChunk 映射，不依赖真库。
- QA-0010：build_runtime 按 Settings.rag_store 装配——pgvector 缺 DSN 快速失败（ConfigError），
  有 DSN 则装配 PgVectorStore（构建期零 IO）；默认仍是 InMemoryVectorStore。
"""

from typing import Any

import pytest

from rfq_copilot.app.infra_pgvector import PgVectorStore
from rfq_copilot.config.settings import get_settings
from rfq_copilot.core.rag.chunking import Chunk
from rfq_copilot.ports.errors import ConfigError


class FakeConn:
    """asyncpg.Connection 最小替身：记录语句、返回可构造的行。"""

    def __init__(self, fetch_rows: list[dict[str, Any]] | None = None) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.fetch_rows = fetch_rows or []
        self.fetchval_result: Any = 0
        self.delete_status = "DELETE 3"

    async def execute(self, sql: str, *args: Any) -> str:
        self.executed.append((sql, args))
        if "DELETE" in sql:
            status, self.delete_status = self.delete_status, "DELETE 0"
            return status
        return "INSERT 0 1"

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        self.executed.append((sql, args))
        return self.fetch_rows

    async def fetchval(self, sql: str, *args: Any) -> Any:
        self.executed.append((sql, args))
        return self.fetchval_result

    async def close(self) -> None:
        self.closed = True


@pytest.fixture()
def fake_connect(monkeypatch: pytest.MonkeyPatch) -> FakeConn:
    conn = FakeConn()

    async def _connect(_dsn: str) -> FakeConn:
        return conn

    # infra_pgvector 在方法内 `import asyncpg`（sys.modules 解析），patch 模块属性
    import asyncpg

    monkeypatch.setattr(asyncpg, "connect", _connect)
    return conn


@pytest.fixture()
def clean_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """隔离 RAG 装配相关 env 并清 Settings 缓存。"""
    import os

    for key in ("RAG_STORE", "RAG_PGVECTOR_DSN", "ADAPTER", "KNOWLEDGE_DATA_DIR"):
        os.environ.pop(key, None)
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()


def _chunk() -> Chunk:
    return Chunk("doc-1", 0, "标题", "内容", "platform", supplier_id="s-001")


async def test_add_inserts_one_row_per_chunk(fake_connect: FakeConn) -> None:
    store = PgVectorStore("postgresql://u:p@h:5432/db")
    added = await store.add([_chunk()], [[0.1] * 1024])
    assert added == 1
    sql, args = fake_connect.executed[-1]
    assert "INSERT INTO knowledge_chunks" in sql
    assert args[0] == "doc-1"
    assert len(args[5]) > 0  # vector literal


async def test_add_rejects_length_mismatch(fake_connect: FakeConn) -> None:
    store = PgVectorStore("postgresql://u:p@h:5432/db")
    with pytest.raises(ValueError, match="mismatch"):
        await store.add([_chunk()], [[0.1] * 1024, [0.2] * 1024])


async def test_search_maps_scored_chunks(fake_connect: FakeConn) -> None:
    row = {
        "doc_id": "doc-1",
        "chunk_index": 0,
        "title": "标题",
        "content": "内容",
        "metadata": '{"trust_level": "platform", "supplier_id": "s-001"}',
        "score": 0.87,
    }
    fake_connect.fetch_rows = [row]
    store = PgVectorStore("postgresql://u:p@h:5432/db")
    hits = await store.search([0.1] * 1024, top_k=3, trust_levels={"platform"})
    assert len(hits) == 1
    assert hits[0].score == pytest.approx(0.87)
    assert hits[0].chunk.trust_level == "platform"
    assert hits[0].chunk.supplier_id == "s-001"
    sql, _ = fake_connect.executed[-1]
    assert "1 - (embedding <=>" in sql  # 距离→相似度
    assert "<=>" in sql  # pgvector 余弦排序（HNSW 路径），非全库 Python 扫描


async def test_search_without_trust_filter(fake_connect: FakeConn) -> None:
    fake_connect.fetch_rows = []
    store = PgVectorStore("postgresql://u:p@h:5432/db")
    hits = await store.search([0.1] * 1024, top_k=5)
    assert hits == []


async def test_remove_and_count(fake_connect: FakeConn) -> None:
    store = PgVectorStore("postgresql://u:p@h:5432/db")
    assert await store.remove_by_doc_id("doc-1") == 3
    fake_connect.fetchval_result = 42
    assert await store.count() == 42
    assert await store.remove_by_doc_id("missing") == 0


async def test_init_ddl_runs_hnsw_index(fake_connect: FakeConn) -> None:
    store = PgVectorStore("postgresql://u:p@h:5432/db")
    await store.init_ddl()
    ddl = " ".join(sql for sql, _ in fake_connect.executed)
    assert "USING hnsw" in ddl
    assert "CREATE TABLE IF NOT EXISTS knowledge_chunks" in ddl


def test_store_requires_dsn() -> None:
    with pytest.raises(ConfigError, match="DSN"):
        PgVectorStore("")


def test_build_runtime_defaults_to_inmemory(clean_settings: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from rfq_copilot.app.infra_pgvector import PgVectorStore as _PVS  # noqa: F401
    from rfq_copilot.app.runtime import build_runtime
    from rfq_copilot.core.rag.store import InMemoryVectorStore

    runtime = build_runtime()
    assert isinstance(runtime.deps.rag._store, InMemoryVectorStore)  # noqa: SLF001


def test_build_runtime_pgvector_requires_dsn(clean_settings: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from rfq_copilot.app.runtime import build_runtime

    monkeypatch.setenv("RAG_STORE", "pgvector")
    monkeypatch.setenv("RAG_PGVECTOR_DSN", "")
    get_settings.cache_clear()
    with pytest.raises(ConfigError, match="DSN"):
        build_runtime()


def test_build_runtime_selects_pgvector_with_dsn(clean_settings: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from rfq_copilot.app.infra_pgvector import PgVectorStore
    from rfq_copilot.app.runtime import build_runtime

    monkeypatch.setenv("RAG_STORE", "pgvector")
    monkeypatch.setenv("RAG_PGVECTOR_DSN", "postgresql://u:p@h:5432/db")
    get_settings.cache_clear()
    runtime = build_runtime()
    assert isinstance(runtime.deps.rag._store, PgVectorStore)  # noqa: SLF001
