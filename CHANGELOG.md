# Changelog

本项目的所有重要变更记录于此文件。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Changed (2026-09-18)

- **适配器与知识资产去品牌化**（ADR-0007，repo-policy 合规）：
  旧适配器包（含站点标识，具名见 git 历史）→ `adapters/vacuum_b2b_offline`；`zzk_*` 模块/类名/
  数据文件名/doc_id 前缀全部中性化；硬编码开发机路径改环境变量 `SUPPLIER_SEEDER_PATH`。
  部署侧需用 `scripts/vacuum_b2b_export.py` 重新导出知识数据。
- CI frontend job 补 `pnpm test`（vitest）+ `pnpm build:widget`（QA-0009）——前端测试与
  嵌入产物自此纳入自动化守护。
- 修复：qa-batch1 合同测试的跨包 import 回归仓库惯例（`from conftest import`），
  消除 CI pytest 收集红。
