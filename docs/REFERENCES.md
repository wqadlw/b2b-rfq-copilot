# REFERENCES · 成熟开源项目参考与借鉴原则

> 密级：公开 · 版本 v1.0 · 2026-09-12 · 宪法 §0 需求二的执行清单
> **原则**：参考成熟项目的架构思想，组合成适合本项目的最佳落地方案——学习而不照抄；**不基于 Dify 配置搭建**（配置平台不构成引擎工程能力）。

## 第一梯队 · 深读架构（直接指导实现）

| 项目 | 借鉴什么 | 落点 |
|---|---|---|
| `langchain-ai/langgraph` | Agent 状态机、条件边、checkpointer、human-in-the-loop | core/agent 图结构与确认门 |
| `infiniflow/ragflow` | 复杂文档解析、分块策略、引用溯源 | core/rag ingestion 与 citation |
| `langfuse/langfuse` | trace 模型（span/生成/评分）、prompt 版本管理 | observability/ 与 prompt_version 机制 |
| `explodinggradients/ragas` | RAG 评测维度（忠实度/答案相关性/上下文 precision） | eval/ A 族 judge 口径 |
| `pgvector/pgvector` | 向量列、HNSW/IVFFlat 索引、混合查询 | M1 prod 形态 |
| `FlagOpen/FlagEmbedding` | bge-m3 稠密+稀疏混合检索、bge-reranker-v2-m3 用法 | core/rag embedding/reranker |

## 第二梯队 · 工程实现参考

| 项目 | 借鉴什么 | 落点 |
|---|---|---|
| `fastapi/fastapi` | 依赖注入、Pydantic 集成、SSE（StreamingResponse） | app/ 组装层 |
| `run-llama/llama_index` | 索引/检索器/查询引擎的抽象分层 | core/rag 接口切分 |
| `confident-ai/deepeval` | LLM 应用断言组织、用例/指标解耦 | rfq_copilot/eval 结构 |
| `vercel/ai-chatbot` | 流式消息 UI、消息状态机 | frontend chat 组件 |
| `Yonom/assistant-ui` | React 聊天组件部件化（消息/工具调用/引用插槽） | ChatWidget 部件设计 |

## 第三梯队 · 业务形态参考（只看形态，不抄实现）

| 项目 | 看什么 |
|---|---|
| `chatwoot/chatwoot` | 客服会话生命周期、人工接管工作台 |
| `frappe/helpdesk` | 工单状态机与协作 |
| `langgenius/dify` | 知识库产品形态、应用编排的产品化表达 |

## 技术路线（冻结）

LangGraph · FastAPI · Pydantic v2 · PostgreSQL+pgvector · bge-m3 / bge-reranker-v2-m3 · SSE · PostgresSaver · capability manifest · 程序化断言评测（负向用例自动派生）· Langfuse · React 19 + Tailwind v4 + shadcn/ui + Lucide。选型理由与备选取舍见 `adr/`。

---
*维护者：工程组 · 新增参考项目须注明"借鉴点与落点"，拒绝无目的堆砌*
