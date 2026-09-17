"""Unit: postgres checkpointer 后端（配置契约与大声失败语义）。

pytest 配置 asyncio_mode=auto：async 测试直接 await。

本机无 PG 时不做真实连接测试——验证的是配置契约：
DSN 缺失必须 ConfigError（半配置静默降级是生产事故源），memory/sqlite 不受影响。
真实 PG 连通性测试在部署环境跑（scripts/smoke_postgres_checkpointer.py）。
"""

import pytest

from rfq_copilot.app.runtime import build_runtime, close_checkpointer, init_checkpointer
from rfq_copilot.config.settings import Settings
from rfq_copilot.ports.errors import ConfigError


async def test_postgres_without_dsn_fails_loudly() -> None:
    runtime = build_runtime()
    with pytest.raises(ConfigError, match="CHECKPOINTER_POSTGRES_DSN"):
        await init_checkpointer(runtime, Settings(checkpointer_backend="postgres"))


async def test_unknown_backend_still_rejected() -> None:
    runtime = build_runtime()
    with pytest.raises(ConfigError, match="expected memory"):
        await init_checkpointer(runtime, Settings(checkpointer_backend="oracle"))


async def test_sqlite_backend_unchanged_by_postgres_wiring(tmp_path) -> None:
    """回归：postgres 分支加入后，sqlite 路径行为不变。"""
    runtime = build_runtime()
    await init_checkpointer(
        runtime,
        Settings(checkpointer_backend="sqlite", checkpointer_sqlite_path=str(tmp_path / "cp.sqlite")),
    )
    assert runtime.checkpointer_conn is not None
    await close_checkpointer(runtime)
    assert runtime.checkpointer_conn is None
