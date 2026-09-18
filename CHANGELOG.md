# Changelog

本项目的所有重要变更记录于此文件。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

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
