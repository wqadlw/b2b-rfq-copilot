"""InquiryStatusPort (阶段三·三)：询盘状态查询（只读）。

按 session_id 查询该会话创建的询盘及进展——session_id 即游客凭证，
无需登录即可查自己会话产生的询盘（不泄露其它会话数据）。
"""

from __future__ import annotations

from typing import Any, Protocol


class InquiryStatusPort(Protocol):
    async def by_session(self, session_id: str) -> dict[str, Any]:
        """返回 {"items": [...], "total": int}；items 为状态摘要（不含敏感字段）。"""
        ...
