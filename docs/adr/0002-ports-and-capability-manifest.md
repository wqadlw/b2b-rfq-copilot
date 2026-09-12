# ADR-0002 · 端口抽象与能力清单（Ports & Capability Manifest）

> 公开 ADR（内部编号 ADR-002/003/004 合并精选）· 日期：2026-09-12 · 状态：已采纳

## 背景

引擎需要接入不同垂直行业 B2B 平台（产品库/供应商/询盘/线索分发形态各异），且部分平台没有公开价格、货期等数据源。

## 决策

1. **五个端口**：ProductCatalog / SupplierDirectory / KnowledgeSource / InquirySink / LeadDistribution；Core 只依赖端口，Adapters 只实现端口（import-linter 强制单向依赖）。
2. **pricing/lead_time/stock 是 capability 不是端口**——它们是"站点有没有这个数据源"的开关，不构成业务流程端口；manifest 必须显式声明三项（禁止缺省）。
3. **Capability manifest 是运行时唯一事实源**：禁用能力 → 工具物理不注册进 LLM 工具列表 → 拒绝话术模板自动注入 → 负向评测用例（B 族）自动派生。
4. 端点 `/api/v1/ui-config` 由后端从 manifest 渲染下发，前端不读 YAML。

## 备选方案

- 站点特判硬编码在 Core（否决：不可泛化，污染引擎）。
- 每站点 fork 引擎（否决：维护成本指数级）。
- 提示词手写能力描述（否决：与装配状态漂移）。

## 后果

- 新行业接入 = 一个 adapter 包 + manifest，Core 零改动。
- 禁用能力与拒绝策略、评测用例永不脱节。
- 一期端口封顶 5 个，新增须走新 ADR。
