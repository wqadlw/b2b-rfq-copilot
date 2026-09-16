"""Integration: durable checkpointer — interrupt()/resume survives a process restart.

Evidence discipline: the sqlite test proves survival with a fresh saver over the same
file; the memory test is the counterfactual showing the same restart loses the pending
confirmation. Together they isolate the durability mechanism.
"""

import contextlib

import aiosqlite
import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from conftest import make_deps, understanding
from rfq_copilot.app.runtime import build_runtime, close_checkpointer, init_checkpointer
from rfq_copilot.config.settings import Settings
from rfq_copilot.core.agent.graph import build_graph
from rfq_copilot.ports.errors import ConfigError

pytestmark = pytest.mark.asyncio

THREAD = "restart-1"
CONFIG = {"configurable": {"thread_id": THREAD}}
STATE = {
    "session_id": THREAD,
    "message": "询价 demo-p-001，10 台。",
    "quantity": 10,
    "product_id": "demo-p-001",
    "contact": {"name": "张三", "phone": "13800000000"},
}


async def _open_sqlite_saver(path) -> tuple[aiosqlite.Connection, AsyncSqliteSaver]:
    conn = await aiosqlite.connect(str(path))
    saver = AsyncSqliteSaver(conn)
    await saver.setup()
    return conn, saver


async def test_sqlite_interrupt_survives_restart(tmp_path) -> None:
    """Pause on the confirmation gate, drop the process, resume from the same file."""
    db = tmp_path / "checkpoints.sqlite"

    deps1, ports1 = make_deps(scripted=[understanding("product_inquiry", "inquiry_flow")])
    conn1, saver1 = await _open_sqlite_saver(db)
    graph1 = build_graph(deps1, checkpointer=saver1)
    first = await graph1.ainvoke(STATE, CONFIG)
    assert first.get("__interrupt__"), "expected pause on the confirmation gate"
    assert ports1.store.inquiries == []  # gate holds before explicit confirm
    await conn1.close()  # simulated shutdown

    deps2, ports2 = make_deps(scripted=[understanding("product_inquiry", "inquiry_flow")])
    conn2, saver2 = await _open_sqlite_saver(db)
    graph2 = build_graph(deps2, checkpointer=saver2)
    resumed = await graph2.ainvoke(Command(resume={"action": "confirm_inquiry"}), CONFIG)
    assert "inquiry_created" in [e for e, _ in resumed["events"]]
    assert len(ports2.store.inquiries) == 1
    await conn2.close()


async def test_memory_counterfactual_loses_pending_interrupt() -> None:
    """Counterfactual: MemorySaver after a 'restart' cannot resume the pending gate."""
    deps1, _ = make_deps(scripted=[understanding("product_inquiry", "inquiry_flow")])
    graph1 = build_graph(deps1, checkpointer=MemorySaver())
    await graph1.ainvoke(STATE, CONFIG)

    deps2, ports2 = make_deps(scripted=[understanding("product_inquiry", "inquiry_flow")])
    graph2 = build_graph(deps2, checkpointer=MemorySaver())
    with contextlib.suppress(Exception):  # langgraph raises: no checkpoint for the thread
        await graph2.ainvoke(Command(resume={"action": "confirm_inquiry"}), CONFIG)
    assert ports2.store.inquiries == []


async def test_init_checkpointer_memory_is_noop() -> None:
    runtime = build_runtime()
    before = runtime.graph
    await init_checkpointer(runtime, Settings(checkpointer_backend="memory"))
    assert runtime.graph is before
    assert runtime.checkpointer_conn is None


async def test_init_checkpointer_sqlite_swaps_graph_and_creates_tables(tmp_path) -> None:
    runtime = build_runtime()
    before = runtime.graph
    db = tmp_path / "nested" / "cp.sqlite"  # parent dir must be created
    await init_checkpointer(
        runtime,
        Settings(checkpointer_backend="sqlite", checkpointer_sqlite_path=str(db)),
    )
    assert db.exists()
    assert runtime.graph is not before
    conn = runtime.checkpointer_conn
    assert conn is not None
    async with conn.execute("SELECT name FROM sqlite_master WHERE type='table'") as cur:
        names = {row[0] async for row in cur}
    assert {"checkpoints", "writes"} <= names
    await close_checkpointer(runtime)
    assert runtime.checkpointer_conn is None


async def test_init_checkpointer_rejects_unknown_backend() -> None:
    runtime = build_runtime()
    with pytest.raises(ConfigError):
        await init_checkpointer(runtime, Settings(checkpointer_backend="postgres"))
