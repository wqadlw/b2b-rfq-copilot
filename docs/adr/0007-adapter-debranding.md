# ADR-0007: 适配器与知识资产去品牌化（de-branding）

- 状态：Accepted
- 日期：2026-09-18
- 关联：docs/policies/repo-policy.md（权威）· QA 审计批次2 · repo policy check 自 PR #2 起在 master 红

## 背景

repo policy 扫描器（"private site name" 规则）自 `ai/glm/zzk-knowledge-export` 合入后持续红
（58 处命中、22 文件）：知识导出战役把私有站点标识（`zhaozhenkong`、`昊志机械`、`zzk` 前缀、
本机绝对路径）带进了公开仓库的适配器包名、import 路径、数据文件名、doc_id 前缀、docstring、
测试与脚本。master CI 因此 4 天处于"门禁失效"状态——红着的门禁等于没有门禁。

policy §2 明文：真实生产域名、内部路径、站点私有实现细节永不进入本仓库。加白名单是掩耳盗铃
（GitHub 上目录名与文件名照样可见），唯一正解是去品牌化重构。

## 决策

1. **包改名**：`adapters/zhaozhenkong_offline/` → `adapters/vacuum_b2b_offline/`
   （与姊妹适配器 `vacuum_b2b_sample` 同族命名）。
2. **模块去前缀**：`zzk_catalog/zzk_cases/zzk_solutions/zzk_suppliers.py` → `catalog/cases/solutions/suppliers.py`。
3. **类名去前缀**：`Zzk*` → `Offline*`（OfflineProductCatalog / OfflineCaseDirectory /
   OfflineSolutionDirectory / OfflineSupplierDirectory）；工厂函数 `load_zzk_catalog` → `load_offline_catalog`。
4. **数据契约改名**（脚本产物 ↔ 适配器装载两侧同步）：
   `zzk_knowledge.json` → `knowledge.json`；`zzk_search_meta.json` → `search_meta.json`；
   `zzk_cases.json` → `cases.json`；`zzk_solutions.json` → `solutions.json`；
   doc_id 前缀 `zzk-*` → `offline-*`；输出目录 `zzk_rag_data` → `rag_data`。
5. **路径泄密修复**：`suppliers.py` 硬编码开发机绝对路径
   `D:\AAAAA\zhaozhenkong\...` → 环境变量 `SUPPLIER_SEEDER_PATH`（缺省相对占位路径，
   文件缺失时回退 knowledge.json——与原行为一致）。
6. **示例域中性化**：CORS 注释/测试/.env.example/ADR-0005 中的站点域名 → `your-domain.com`。
7. **前端中性化**：cardMapper 测试供应商名、widget 默认欢迎语去站点品牌。
8. **导出标记改名**：`ZZKMETA_BEGIN/END` → `SITEMETA_BEGIN/END`（⚠ 需站点侧 SearchService
   注入标记同步改名，一次性协调项）。
9. **CI 补齐（QA-0009）**：frontend job 增加 `pnpm test`（vitest 12 用例）+ `pnpm build:widget`
   （嵌入产物）两道门，前端测试与产物自此有自动化守护。

## 后果

- 行为无语义变化：改名是纯机械重构，pytest/eval 全量回归保证等价。
- **部署协调项**：已生成的旧导出数据（`zzk_*.json`、`zzk-*` doc_id）需用新脚本重新导出
  （`scripts/vacuum_b2b_export.py`），否则运行时找不到 `knowledge.json`。
- 站点侧 `SearchService.php` 的 `ZZKMETA_*` 标记注释需同步改为 `SITEMETA_*`。
- 公开仓库自本 ADR 起不再携带任何私有站点标识；repo policy check 回到可执行状态。
