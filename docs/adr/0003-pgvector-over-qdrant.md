# ADR-0003 · 向量检索选 pgvector 而非 Qdrant

> 公开 ADR（内部编号 ADR-006 精选）· 日期：2026-09-12 · 状态：已采纳

## 背景

知识库检索需要向量库；候选 Qdrant（独立服务）与 pgvector（PostgreSQL 扩展）。

## 决策

生产形态统一 **PostgreSQL 16 + pgvector（HNSW 索引）**：业务数据、`ai.*` 会话/Trace schema、LangGraph 检查点、向量索引同库。Demo 形态 SQLite + BM25 词法检索降级（`--profile prod` 切换）。

## 备选方案

- Qdrant：检索性能与过滤能力强，但 solo/中小数据量级下多运维一个组件不值。
- Milvus/Weaviate：同上，更重。
- Elasticsearch：为检索引入整条 ES 栈，过度。

## 后果

- 部署面少一个有状态服务；事务一致性（知识块与元数据）天然获得。
- 数据量级（行业知识库 ≤ 百万 chunk）pgvector 完全够用。
- Demo 十分钟验收线只需 1 个 LLM Key（BM25 降级不需 embedding 服务）。
