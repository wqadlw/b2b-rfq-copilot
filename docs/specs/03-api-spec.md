# 03 · API SPEC · 对外服务契约

> 密级：公开 · 版本 v1.0 · 2026-09-12 · 上位文档：`01-port-spec.md`（端口与事件语义权威）；错误码与 SSE 事件清单承自 port-spec §8，本文定义 HTTP 形状与载荷。

## 0. 约定

- Base URL：`/api/v1`；所有请求/响应 `Content-Type: application/json`（SSE 为 `text/event-stream`）。
- 版本：URL 大版本（`/api/v1`）；破坏性变更升 `/api/v2`。
- 错误响应统一：`{"code": "<错误码>", "message": "<人读>", "details": {...}}`，错误码表见 port-spec §8。
- 认证：公开聊天接口**无用户鉴权**（游客可聊），以 `session_id` + 服务端签发的会话令牌（`POST /sessions` 返回）绑定；写操作（询盘）受站点侧政策约束（`guest_allowed`）。

## 1. 会话

### POST /api/v1/sessions — 创建会话

```json
// 请求
{ "page_type": "product_detail", "page_url": "/products/123", "product_id": "123", "category_id": "4", "visitor_id": "anon_xxx", "user_ref": null }
// 响应 201
{ "session_id": "sess_xxx", "token": "<会话令牌>", "ui": { /* 同 GET /ui-config */ } }
```

### GET /api/v1/sessions/{session_id}/messages — 会话历史

```json
{ "messages": [ { "id": "msg_001", "role": "user|assistant", "content": "…", "citations": [ { "doc_id": "kb_001", "title": "…", "section": "…", "trust": "platform" } ], "tool_calls": ["search_products"], "created_at": "…" } ], "has_more": false }
```

## 2. 聊天（SSE 流式）

### POST /api/v1/chat/stream

```json
// 请求
{ "session_id": "sess_xxx", "message": "我需要一台无油真空泵，抽速 100 m³/h", "page_type": "product_detail", "product_id": "123" }
```

响应：`text/event-stream`，事件顺序（port-spec §8 全集）：

| event | data 载荷 | 说明 |
|---|---|---|
| `status` | `{"message": "正在理解您的需求"}` | 阶段提示（前端状态条） |
| `tool_call` | `{"tool": "search_products", "status": "running\|done"}` | 工具调用可见化 |
| `retrieval` | `{"count": 4, "sources": [{"doc_id","title","trust"}]}` | 检索完成（trust=信任等级） |
| `answer_delta` | `{"delta": "根据站内资料，"}` | 增量正文（拼接渲染） |
| `citation` | `{"doc_id","title","section","trust","url?"}` | 单条引用（answer 中标注） |
| `inquiry_confirm` | `{"confirm_id": "cfm_xxx", "draft": {产品/数量/需求摘要/联系人摘要/缺失字段}}` | **确认门**：请求用户显式确认询盘草稿 |
| `inquiry_created` | `{"inquiry_id": "1001", "state": "created"}` | 询盘创建成功（确认门通过后） |
| `handoff` | `{"reason": "complex_selection", "priority": "high"}` | 转人工 |
| `error` | `{"code": "UPSTREAM_TIMEOUT", "message": "…"}` | 错误（码表见 port-spec §8；Policy 类结果不走 error，走正常内容/模板） |
| `done` | `{"finish_reason": "answered\|inquiry_created\|handoff\|error"}` | 流结束 |

**确认交互**：客户端收到 `inquiry_confirm` 后渲染确认卡片；用户确认后携带 `confirm_id` 发起下一轮 `POST /chat/stream`（`message` 置空、`action: "confirm_inquiry"` 或 `"cancel_inquiry"`）。草稿变更（改数量/联系方式）= 新一轮澄清，重新出 `inquiry_confirm`。

## 3. Widget 配置

### GET /api/v1/ui-config

由 runtime 从 manifest 渲染（**manifest 是 UI 唯一事实源**，前端不读 YAML）：

```json
{
  "adapter": "demo",
  "display_name": "Demo B2B Platform",
  "chat": { "welcome_message": "…", "suggested_questions": ["…"] },
  "theme": { "primary": "#2563EB" },
  "capabilities": { "product_catalog": true, "supplier_directory": true, "knowledge_source": true, "inquiry": true, "lead_distribution": true, "pricing": false, "lead_time": false, "stock": false },
  "inquiry": { "guest_allowed": true, "required_fields": ["contact_name", "contact_phone"] },
  "i18n": "zh-CN"
}
```

前端据 `capabilities` 渲染能力徽章（含禁用态）；`theme.primary` 为 manifest 白标预留（ADR-008，M4 实装）。

## 4. 反馈与健康

### POST /api/v1/feedback

```json
{ "session_id": "sess_xxx", "message_id": "msg_001", "feedback": "helpful|not_helpful", "comment": "可选" }
```

### GET /api/v1/health → `{"status":"ok","adapter":"demo","profile":"demo|prod"}`

（能力徽章数据不单设 `/capabilities` 端点，统一由 `GET /api/v1/ui-config` 的 `capabilities` 键承载——manifest 是唯一事实源。）

## 5. 限流

| 维度 | 默认 | 超限行为 |
|---|---|---|
| 每会话 | 20 轮/小时 | 429 `RATE_LIMITED` |
| 每 IP | 60 轮/小时 | 同上 |
| 每 IP（未带会话令牌） | 10 轮/小时 | 强制先建会话 |
| 单会话 token 预算 | 配置项（默认 200k/会话） | 触达后提示并建议转人工 |

生产部署可由反代/网关再加一层；站点侧内部 API 限流由站点实现（不在本契约内）。

## 6. 兼容性承诺

- SSE 事件集合只增不改（新增事件前端须向后兼容忽略未知事件）。
- 响应字段只增不删；语义变更升大版本。
- `ui-config.capabilities` 键与 port-spec manifest 键一一对应。

---
*维护者：工程组 · 变更须同步 port-spec §8 并在 CHANGELOG 登记*
