# 03 · API SPEC · 对外服务契约

> 密级：公开 · 版本 v1.2 · 2026-09-21 · 上位文档：`01-port-spec.md`（端口与事件语义权威）；错误码与 SSE 事件清单承自 port-spec §8，本文定义 HTTP 形状与载荷。

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
| `card` | `{"kind": "product\|supplier\|solution\|case\|inquiry_status\|product_compare", ...}` | 结构化实体卡（kind 实发全集，前端 cardMapper 表驱动消费；`product_compare` 载荷见下节） |
| `inquiry_confirm` | `{"confirm_id": "cfm_xxx", "draft": {产品/数量/工况摘要?/联系人/掩码电话}, "draft_json": "草稿原文 JSON 字符串（向后兼容保留）"}` | **确认门**：请求用户显式确认询盘草稿（`draft.specs` 为可选工况摘要字符串，源自草稿 params 的规格项，P1-4 v1.2 新增；无规格项为 `null`） |
| `inquiry_created` | `{"inquiry_id": "1001", "state": "created"}` | 询盘创建成功（确认门通过后） |
| `handoff` | `{"reason": "complex_selection", "priority": "high"}` | 转人工 |
| `error` | `{"code": "UPSTREAM_TIMEOUT", "message": "…"}` | 错误（码表见 port-spec §8；Policy 类结果不走 error，走正常内容/模板） |
| `wechat_guidance` | `{"guidance": "…", "qrcode_url": "…", "contact_name": "…"}` | 询盘创建后微信一对一引导 |
| `login_required` | `{"reason": "llm_turn", "suggestions": [...]}` | 游客触达需登录功能（0 token 引导，guest tier） |
| `token_budget_exceeded` | `{"user_ref": "..."}` | 当日 token 预算耗尽（引导微信/明日再试） |
| `done` | `{"finish_reason": "answered\|inquiry_created\|handoff\|error\|login_required\|rate_limited\|token_budget_exceeded\|human_serving"}` | 流结束 |

> 事件全集与前端 `frontend/src/lib/types.ts` 的 `ChatEventName` 一一对应（14 名，QA-0006 收敛：后端 Literal == 实发集 == 前端冻结集，表驱动合同测锁定）。

**`product_compare` 卡载荷（v1.1 新增）**：规格匹配（`spec_match_flow`）与产品对比（`compare_flow`）各追加一张对比卡，与既有产品卡并存、不互替。

```json
{
  "kind": "product_compare",
  "title": "按您的规格条件对比",
  "criteria_summary": ["抽速 ≥ 300 m³/h", "极限真空 ≤ 10 Pa"],
  "products": [
    {
      "name": "产品 A", "supplier": "供应商", "price": "¥1,000", "url": "…",
      "matched_on": ["抽速 540 m³/h ≥ 300", "无油 ✓"]
    }
  ],
  "rows": [
    {"label": "抽速", "values": ["540 m³/h", "320 m³/h"], "ok": [true, true], "direction_hint": null},
    {"label": "极限真空", "values": ["0.5 Pa", "8 Pa"], "ok": [true, true], "direction_hint": "更低"}
  ]
}
```

- `criteria_summary`：用户条件的原文口径摘要（可空——compare_flow 无用户数值条件时缺省）。
- `rows[].ok`：该产品该参数是否满足用户条件；无对应条件时可整行缺省 `ok`。
- `rows[].direction_hint`：仅客观方向（"更高/更低"），**不构成推荐结论**（延用 port-spec §3.2 中立纪律）。
- `matched_on`：每款产品一句 grounded 匹配依据（由确定性匹配器生成，**禁止 LLM 生成理由**）。
- 前端对未知 `kind` 须向后兼容回落现有默认卡（suppliers 分支）。

**确认交互**：客户端收到 `inquiry_confirm` 后渲染确认卡片；用户确认后携带 `confirm_id` 发起下一轮 `POST /chat/stream`（`message` 置空、`action: "confirm_inquiry"` 或 `"cancel_inquiry"`）。草稿变更（改数量/联系方式）= 新一轮澄清，重新出 `inquiry_confirm`。

**行内编辑回传（resume 透传，QA-0003）**：确认/取消请求体可携带 `draft_override` 对象，对确认门草稿做白名单合并：

```json
{ "session_id": "sess_xxx", "message": "", "action": "confirm_inquiry", "draft_override": { "quantity": 20, "contact_name": "张三", "contact_phone": "13800000000" } }
```

- 白名单字段：`quantity`（int，0 < q ≤ 100000）/ `contact_name`（str，≤50 字）/ `contact_phone`（数字串 7-20 位）；非白名单键与不合法值**静默忽略**（服务端校验为准，前端不做二次校验依赖）
- 合并发生在 `confirm_inquiry` 通过之后、落库创建之前；合并后缺必填字段 → 重新出 `inquiry_confirm`（带更新后的草稿）
- 未携带 `draft_override` 或为空对象 = 原草稿直接确认，行为不变

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

离线知识模式（`KNOWLEDGE_DATA_DIR` 非空）额外携带语料新鲜度（08-knowledge-export-spec §4/§5）：`"corpus_age_days": <float|null>, "corpus_stale": <bool>`；demo 模式不携带。

### GET /api/v1/health 兜底刷新历史（spec 02-engine-read-api-spec §3）

`refresh_history: [近 7 轮刷新记录]`（末条 == `knowledge_refresh`；未运行为 null）。内存态，重启清零。`knowledge_refresh` 字段保留向后兼容。

### 知识运行时维护（08-knowledge-export-spec §6，全部需 X-Internal-Token）

| 端点 | 说明 |
|---|---|
| `POST /api/v1/knowledge` | 运行时插入/**替换**文档（先移除同 doc_id 文档家族——含 ` (i/n)` 分块后缀——再按新内容重嵌，无需重启）。必填 `doc_id`/`title`/`content`；可选 `doc_type`（默认 platform_faq）、`trust_level`（默认 platform）、`supplier_id`、`product_id`、`params`（`dict[str,str]`，选型过滤元数据，08 规格 §6.4.1 消费）。成功 → `{"doc_id","chunks","replaced_chunks","status":"ingested"}`。坏 JSON/非对象 → 400 INVALID_JSON；缺必填 → 400 MISSING_FIELDS；params 非法 → 400 INVALID_PARAMS；知识库未启用 → 503 PORT_DISABLED |
| `DELETE /api/v1/knowledge/{doc_id}` | 移除该文档全部块；返回 `{"doc_id","removed","status":"removed"}` |

**调用方契约（站点 webhook，阶段 3）**：doc_id 必须与导出脚本命名一致，保证运行时更新与每日兜底重导可对账。前缀全集：产品=`offline-product-{slug}`；CMS 内容（阶段 3.2，`offline-{复数源名}-{slug}`）=文章 `offline-articles-{slug}`、方案 `offline-solutions-{slug}`、案例 `offline-cases-{slug}`、洞察 `offline-insights-{slug}`、服务 `offline-services-{slug}`。信任等级：平台内容（文章/方案/洞察）`platform`；供应商绑定内容（案例/服务）`merchant` + `supplier_id`。slug 即 doc_id 的一部分：slug 变更须先 DELETE 旧 doc_id 再 POST 新 doc_id；非发布态一律 DELETE。站点侧失败仅告警不阻断内容保存（fail-open）。

---

## 7. 运营只读端点（A-01，authority: 中枢仓 docs/specs/02-engine-read-api-spec.md，全部需 X-Internal-Token）

> 消费方=找真空运营中枢网关(:8002)。feedback 端点为唯一例外改动（存储层真存，请求契约不变）。

### 反馈（spec 02 §1.1）

| 端点 | 说明 |
|---|---|
| `POST /api/v1/feedback`（公开） | 请求契约不变；**响应新增 `id`**（uuid12）。存储 `{id,ts,seq,session_id,message_id,feedback,comment}`；`RUNTIME_DATA_DIR` 非空时落 `<dir>/feedback.jsonl`（启动回放，重启不丢），空=纯内存 |
| `GET /api/v1/feedback?feedback=&session_id=&limit=&offset=` | `{items[ts倒序], total}` |
| `GET /api/v1/feedback/stats?period=today\|week\|month` | `{period,helpful,not_helpful,total,by_day[]}` |

### 缺口事件（spec 02 §1.2）

| 端点 | 说明 |
|---|---|
| `GET /api/v1/no-match-events?route=&limit=&offset=` | `{items:[{ts,session_id,question,route,keyword?}], total}` |
| `GET /api/v1/no-match/stats?period=` | `{period,total,by_route,by_day,top_questions≤10}` |

产生路径（GraphDeps.no_match_recorder 注入，**不走 SSE 事件通道**——事件名冻结集 QA-0006）：product_flow 零命中（route=product_flow）与 knowledge_flow 零召回（route=knowledge_flow）。落 `no_match_events.jsonl`。

### knowledge 只读四端点（spec 02 §2；v1 仅 inmemory，pgvector → 503 ADMIN_UNSUPPORTED）

| 端点 | 说明 |
|---|---|
| `GET /api/v1/knowledge/stats` | `{documents,chunks,by_doc_type,by_trust_level,rag_store,corpus{age_days,stale,doc_count,source}|null}`；文档数=家族去重（剥 ` (i/n)` 后缀） |
| `GET /api/v1/knowledge/docs?q=&trust=&doc_type=&page=&page_size=` | 家族条目列表（doc_id 字典序）：`{items:[{doc_id,title,doc_type,trust_level,chunk_count,supplier_id,product_id,category_id,params,content_hash,hash_source}],page,page_size,total}`。`hash_source=manifest`（离线 export_manifest.json 真值）|`reconstructed`（分块重建 sha256，超长段硬切边缘用例可能与站点侧不一致——对账以存在性+chunk_count 兜底）。**无时间戳（数据缺口，v1 不提供）** |
| `GET /api/v1/knowledge/docs/{doc_id}` | 404 KNOWLEDGE_NOT_FOUND；`{doc:<同上>,chunks:[chunk_index 升序]}`；base/带后缀 doc_id 均可查 |
| `POST /api/v1/knowledge/test-retrieval` | 入参 `{query,top_k=5,score_threshold=0.0,entities?}`（entities=scan_spec_entities 形态→SpecCriteria）；出参 `{query,rag_store,count,records:[{doc_id,chunk_doc_id,chunk_index,title,content,trust_level,score}],routing:{predicted_route,signals}}`。**score=RRF 融合分（Σ1/(60+rank)，非余弦）**；免 LLM；走 search_scored 专用路径，**不触发命中统计** |
| `GET /api/v1/knowledge/hit-stats?days=1~90` | `{days,series:[{date,doc_id,hits}],total_by_doc}`；记录点=RAGPipeline.search() final top-k 去重 doc_id；落 `hit_stats.json`（重启不丢） |

### 兼容性承诺

- 以上全部为**新增**端点/字段，不改动任何既有端点行为（feedback 响应新增 id 为增量）。
- Chunk 新增 `doc_type` 透传字段（缺省 None→统计归 unknown）；`rrf_fuse` 改为 `rrf_fuse_scored` 薄委托（行为不变）。

## 4.5 坐席接管（CS-1，全部需 X-Internal-Token）

会话状态机：`bot_serving`（AI 服务中）→ `handoff_pending`（待人工接管，handoff 路由或**用户侧转人工**触发）→ `human_serving`（人工服务中）→ `closed`（已结束）。状态存于 SessionStore，随会话生命周期存在。

| 端点 | 说明 |
|---|---|
| `GET /api/v1/agent/sessions?status=handoff_pending` | 坐席工作台会话列表（按状态过滤，最近消息优先）；非法 status → 400 INVALID_STATUS |
| `POST /api/v1/agent/sessions/{id}/takeover` | 接管：→ `human_serving`，写入系统消息"坐席已接入"；会话不存在或已结束 → 404 |
| `POST /api/v1/agent/sessions/{id}/reply` | 坐席回复：`{"content": "..."}`（≤2000 字符）直接落会话消息流（role=agent），**不进 LLM**；会话不在 `human_serving` → 409 NOT_HUMAN_SERVING；坏 JSON → 400 INVALID_JSON；空内容 → 400 MISSING_CONTENT |
| `POST /api/v1/agent/sessions/{id}/close` | 结束：→ `closed`，写入系统消息"本次服务已结束"；不存在 → 404 |
| `POST /api/v1/sessions/{id}/handoff-request` | **用户侧转人工（公开，session_id 即凭证，与询盘状态查询同信任级）**：`bot_serving` → `handoff_pending` 并落系统消息；`handoff_pending`/`human_serving` → 幂等 200（不重复落消息）；`closed` → 409 SESSION_CLOSED；不存在 → 404。无 LLM 成本，幂等即防滥用，不设额外限流 |

**human_serving 绕过语义**：会话处于 `human_serving` 时，用户经 `POST /chat/stream` 发送的消息**绕过 LLM 图（0 token）**：用户消息照常落库，SSE 返回 `status`（人工服务中）+ 最后一条坐席回复的 `answer_delta` + `done(finish_reason="human_serving")`。坐席消息经 reply 落库后，用户下次轮询/发消息即见。

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
