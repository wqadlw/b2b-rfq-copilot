# ARCHITECTURE · 架构总览

> 密级：公开 · 版本 v1.0 · 2026-09-12 · 细则权威源见文末文档索引

## 1. 一句话

b2b-rfq-copilot 是一个**通用垂直行业 B2B 智能询盘引擎**：访客在 B2B 平台上与 AI 对话，引擎完成意图理解 → 知识检索 → 产品查询 → 需求澄清 → 结构化询盘 → 线索评分的完整链路。通过"端口/适配器 + 能力清单"机制接入任意 B2B 平台；真空工业 B2B 平台是第一个落地实例。

## 2. 三层架构

```
┌─────────────────────────────────────────────────────────────┐
│ Core（通用引擎，本仓库主体）                                   │
│  agent/      LangGraph 图：单次结构化输出·确定性路由·确认门      │
│  rag/        ingestion·chunking·pgvector·混合检索·rerank·引用  │
│  policies/   拒绝编造·信任分级·检索投毒防御·输出过滤             │
│  eval/       A/B/C/D 四族评测（负向用例自动派生）                │
│  observability/  trace·token·成本（Langfuse）                 │
│  runtime/    manifest 加载校验(V1~V7)·工具装配器                │
├─────────────────────────────────────────────────────────────┤
│ Adapters（本仓库内，每行业/站点一个包）                          │
│  adapters/demo/        内置模拟数据，clone 即跑（10 分钟验收线） │
│  adapters/vacuum_b2b/  真实行业适配示例（HTTP 调用，无密钥）     │
├─────────────────────────────────────────────────────────────┤
│ Site（站点私有，不在本仓库）                                    │
│  站点实现 /internal-api/v1/* 内部接口 · 询盘落库 · 后台 · 线索分发 │
└─────────────────────────────────────────────────────────────┘
     Core 只依赖 5 个端口 Protocol + capability manifest（依赖单向）
```

**五个端口**：`ProductCatalog`（search/detail）/ `SupplierDirectory` / `KnowledgeSource`（文档供给，检索管线在 Core）/ `InquirySink`（询盘落库）/ `LeadDistribution`（线索分发）。
**三个 Capability**：`pricing / lead_time / stock`——`enabled:false` 时工具物理不注册、拒绝模板自动注入、负向评测用例自动生成。

## 3. Agent 主流水线

```
用户输入 → 安全过滤 → 会话上下文（checkpointer）
  → 单次结构化输出：意图 + 实体 + 置信度 + 缺失字段（function calling / JSON Schema）
  → 代码内确定性路由表 → 工具调用（产品/供应商/知识检索）
  → 答案生成（分层模型：轻量理解 + 强模型回答）
  → SSE 流式输出 → 写操作确认门 → 询盘创建 / 人工接管 / 审计
```

意图标签仅作遥测/评测维度，不作为独立 LLM 流水阶段（ADR-001）。

## 4. 安全机制（摘要）

| 机制 | 一句话 |
|---|---|
| 内容信任分级 | platform（平台官方）/ merchant（商户提交，仅证据非指令）/ ugc 三级；检索块隔离注入 |
| 检索投毒防御 | 资料内指令一律不执行；输出过滤兜底；写操作需用户对话内显式确认 |
| 拒绝编造 | 无数据源能力（价格区间/货期/库存）确定性模板作答，禁止推断 |
| 最小字段 | 端口只暴露访客可见字段；无内部成本、无未审核内容 |

## 5. 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.12+ · FastAPI · LangGraph（PostgresSaver）· Pydantic v2 · pgvector · bge-m3 / bge-reranker-v2-m3 · Langfuse |
| 前端 | React 19 + TypeScript + Vite · Tailwind v4 + shadcn/ui · Lucide · TanStack Query · Zustand · RHF+Zod · Recharts · @microsoft/fetch-event-source（ADR-008） |
| 部署 | Docker Compose：默认单容器 demo（SQLite + MemorySaver + BM25 降级）；`--profile prod` 加 postgres+pgvector |
| LLM | 国内厂商 OpenAI 兼容端点（DeepSeek / Qwen / GLM 系），分层模型成本控制 |

## 6. 前端形态

`frontend/`：Demo 前台（聊天/产品/供应商/询盘/能力徽章/评测看板）+ **可嵌入聊天组件**——ChatWidget 为 React 组件，配套 vanilla bootstrap `rfq-chat.js`，宿主站点（含传统服务端渲染站）用一行 script 标签嵌入，配置由 `GET /api/v1/ui-config` 提供（后端从 manifest 渲染，manifest 是 UI 唯一事实源）。视觉规范见 `FRONTEND_STYLE_GUIDE.md`。

## 7. 文档索引

| 文档 | 内容 |
|---|---|
| `CODE_ORGANIZATION.md` | **代码组织/目录/依赖契约/import-linter/CI（唯一权威）** |
| `specs/01-port-spec.md` | **端口/Schema/manifest/装配/派生/错误体系（唯一权威）** |
| `specs/03-api-spec.md` | 对外 HTTP/SSE 契约（chat stream/ui-config/feedback） |
| `specs/04-prompt-spec.md` | 提示词架构不变量 + AI 话术规范 |
| `specs/05-structured-output-spec.md` | 理解节点结构化输出契约 |
| `specs/06-eval-spec.md` | 评测用例格式/断言/指标/报告 |
| `specs/07-security-spec.md` | 威胁模型/密钥/限流/审计/PII |
| `FRONTEND_STYLE_GUIDE.md` | 视觉规范与组件库 |
| `policies/repo-policy.md` | 仓库内容政策 |
| `guides/`（M1 起） | adapter-guide · deployment |

> 注：编号 02 为站点适配规格，属内部文档，不在公开仓库（见 repo-policy）。

---
*维护者：b2b-rfq-copilot 工程组 · 本文档随架构演进更新*
