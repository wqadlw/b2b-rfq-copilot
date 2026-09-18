"""Postgres checkpointer 部署冒烟：interrupt → 新 saver resume → created。

用法（部署环境，需真实 PG）：
    CHECKPOINTER_BACKEND=postgres CHECKPOINTER_POSTGRES_DSN=postgresql://… \
        uv run python scripts/smoke_postgres_checkpointer.py

验证点：setup() 建表 / aget_tuple 跨 saver 实例可读 / resume 产出 inquiry_created。
环境要求：适配器为 demo（离线数据，不依赖站点）；LLM 用 FakeLLM（scripted）。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "tests"))

import aiosqlite  # noqa: F401  (确保依赖提示一致)

from conftest import make_deps, understanding  # type: ignore[import-not-found]
from rfq_copilot.core.agent.graph import build_graph  # noqa: E402
from rfq_copilot.ports.errors import ConfigError  # noqa: E402


async def main() -> int:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from langgraph.types import Command
    from psycopg_pool import AsyncConnectionPool

    dsn = os.environ.get("CHECKPOINTER_POSTGRES_DSN", "")
    if not dsn:
        print("ERROR CHECKPOINTER_POSTGRES_DSN 未设置")
        return 2

    pool = AsyncConnectionPool(conninfo=dsn, open=False, kwargs={"autocommit": True})
    await pool.open()
    saver = AsyncPostgresSaver(pool)
    await saver.setup()

    deps, ports = make_deps(scripted=[understanding("product_inquiry", "inquiry_flow")])
    graph = build_graph(deps, checkpointer=saver)
    state = {
        "session_id": "pg-smoke-1",
        "message": "询价 demo-p-001，10 台。",
        "quantity": 10,
        "product_id": "demo-p-001",
        "contact": {"name": "冒烟", "phone": "13800000000"},
    }
    cfg = {"configurable": {"thread_id": "pg-smoke-1"}}
    first = await graph.ainvoke(state, cfg)
    if not first.get("__interrupt__"):
        print("FAIL 未在确认卡挂起")
        await pool.close()
        return 1
    print("PASS interrupt 挂起")

    # 新 saver 实例（模拟另一进程）读同一 PG：跨进程持久化
    pool2 = AsyncConnectionPool(conninfo=dsn, open=False, kwargs={"autocommit": True})
    await pool2.open()
    saver2 = AsyncPostgresSaver(pool2)
    deps2, ports2 = make_deps(scripted=[understanding("product_inquiry", "inquiry_flow")])
    graph2 = build_graph(deps2, checkpointer=saver2)
    resumed = await graph2.ainvoke(Command(resume={"action": "confirm_inquiry"}), cfg)
    ok = "inquiry_created" in [e for e, _ in resumed["events"]] and len(ports2.store.inquiries) == 1
    print("PASS resume 跨实例成功" if ok else "FAIL resume 失败")
    await pool.close()
    await pool2.close()
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except ConfigError as exc:
        print(f"ERROR {exc}")
        sys.exit(2)
