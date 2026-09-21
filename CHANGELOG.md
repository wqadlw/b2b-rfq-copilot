# Changelog

本项目的所有重要变更记录于此文件。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added (2026-09-21)

- **P1-4 收官：确认卡工况摘要**：`inquiry_confirm` 卡片 `draft` 新增可选 `specs` 字段
  （`spec_summary` 摘要，03-api-spec v1.2），前端确认卡渲染「工况：…」行；规格摘要/实体
  提取 helper 公共化到 `spec_matcher`（graph 与 sse_mapper 共用），`spec_summary` 无规格项
  返回空串。
- **P1-4 询盘工况带入**：spec_match 提取的规格跨轮累积（spec_context 随 checkpoint 持久化），
  询盘时合并进 draft.params（历史为底、当前轮优先）并在确认话术附工况摘要——先聊规格
  后询盘不再丢工况，供应商拿到的询盘单自带完整参数。询盘快捷路由（0-token 直达）补
  确定性规格扫描 `scan_spec_entities`（显式"关键词+数字+单位"才认，科学计数/区间不猜），
  "改成抽速 500 m3/h，帮我发起询盘"同句规格不再丢失。
- **P1-3 机组组合建议**：`spec_match_flow` 命中高真空（极限真空 ≤ 10 Pa）或大抽速
  （≥ 500 m³/h）工况时，RAG 检索选型指南并**摘录**（≤160 字）一段"系统建议"追加到答案，
  附 citation 引用与 search_knowledge 工具轨迹；摘录不生成（grounded），rag 无召回静默跳过。
- **`product_compare` 对比卡（03-api-spec v1.1）**：`card` 事件新增 `kind: "product_compare"`
  载荷（criteria_summary / products[].matched_on / rows[].ok+direction_hint），
  由 `spec_match_flow`（按用户规格条件对比）与 `compare_flow`（点名两产品矩阵）
  各追加一张，与既有产品卡并存；匹配依据由确定性匹配器生成，禁止 LLM 生成理由。

### Changed (2026-09-18)

- **QA-0007/0010 pgvector 真装配**：`VectorStore` 协议统一 async；新增 `PgVectorStore`
  （HNSW 检索、协议级 add/search/remove/count）；`build_runtime` 按 `RAG_STORE`
  装配（inmemory|pgvector，缺 DSN 快速失败）；pgvector 验收脚本同时验证协议回路。
  生产检索不再是无索引的 Python 余弦扫描（ADR-0003 承诺自此兑现）。
- **QA-0002 注入防护锚点对齐**：检索上下文渲染加 `<retrieved_context>` 外层信封
  （内嵌信任分块不变），system prompt 引用的锚点自此真实存在；新增
  "prompt 引用标签 ⊆ 渲染器产出集" 一致性合同测试（spec §01 6.3 同步）。
- **QA-0008 预算/限流惰性化**：`_BUDGET`/`_LIMITER` 不再 import 期固化，
  惰性跟随 Settings；`reset_rate_limit_state()` 提供显式刷新点。
- **适配器与知识资产去品牌化**（ADR-0007，repo-policy 合规）：
  旧适配器包（含站点标识，具名见 git 历史）→ `adapters/vacuum_b2b_offline`；`zzk_*` 模块/类名/
  数据文件名/doc_id 前缀全部中性化；硬编码开发机路径改环境变量 `SUPPLIER_SEEDER_PATH`。
  部署侧需用 `scripts/vacuum_b2b_export.py` 重新导出知识数据。
- CI frontend job 补 `pnpm test`（vitest）+ `pnpm build:widget`（QA-0009）——前端测试与
  嵌入产物自此纳入自动化守护。
- 修复：qa-batch1 合同测试的跨包 import 回归仓库惯例（`from conftest import`），
  消除 CI pytest 收集红。
