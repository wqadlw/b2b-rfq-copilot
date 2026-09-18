"""AI 助手身份票据：宿主站点签发、copilot 验签（HMAC-SHA256）。

模式参照（2026-09-17 调研）：
- Chatwoot Identity Validation：HMAC-SHA256(identifier, per-inbox-secret)
- Intercom：已从裸 HMAC 迁移到 JWT——采纳其"短时有效 + 服务端签发"设计点，
  保持 HMAC（单宿主对单服务，无需 JWT 标准化开销）。

票据格式：`{user_id}.{expires_at_unix}.{hmac_hex}`，其中
  hmac_hex = HMAC_SHA256(secret, f"{user_id}.{expires_at_unix}").hexdigest()

安全性质：
- 无 secret 不可伪造（防跨用户冒充/会话窃取——Intercom 迁移文档列举的威胁）；
- 5 分钟过期（前端每次会话创建时向宿主索取）；
- 验签用 hmac.compare_digest 防时序攻击。
"""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass

TICKET_TTL_SECONDS = 300  # 5 分钟：会话创建时索取，覆盖 SSE 长连接建立窗口


@dataclass(frozen=True)
class TicketVerifyResult:
    ok: bool
    user_id: str | None = None
    reason: str = ""


def issue_ticket(user_id: str, secret: str, now: int | None = None) -> str:
    """宿主站点侧：为已登录用户签发票据（Laravel 侧同算法实现）。"""
    expires = (now or int(time.time())) + TICKET_TTL_SECONDS
    message = f"{user_id}.{expires}"
    digest = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{message}.{digest}"


def verify_ticket(ticket: str, secret: str, now: int | None = None) -> TicketVerifyResult:
    """copilot 侧验签。任何异常都视为游客（不抛错——票据失败降级为游客语义）。"""
    text = (ticket or "").strip()
    if not text:
        return TicketVerifyResult(ok=False, reason="empty")
    parts = text.split(".")
    if len(parts) != 3:
        return TicketVerifyResult(ok=False, reason="format")
    user_id, expires_raw, digest = parts
    if not user_id or not expires_raw.isdigit() or not digest:
        return TicketVerifyResult(ok=False, reason="format")
    expires = int(expires_raw)
    now_ts = now or int(time.time())
    if now_ts > expires:
        return TicketVerifyResult(ok=False, reason="expired")
    expected = hmac.new(
        secret.encode("utf-8"),
        f"{user_id}.{expires_raw}".encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, digest):
        return TicketVerifyResult(ok=False, reason="bad_signature")
    return TicketVerifyResult(ok=True, user_id=user_id)
