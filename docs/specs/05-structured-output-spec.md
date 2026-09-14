# 05 · STRUCTURED OUTPUT SPEC · 理解节点结构化输出契约

> 密级：公开 · 版本 v1.3 · 2026-09-14 · 关联：路由行为见 `01-port-spec.md` §4；用例断言见 `06-eval-spec.md`

## 1. 定位

理解节点（understanding node）是 Agent 图的第一个 LLM 节点：**单次** function calling / JSON Schema 约束调用，同时完成意图识别 + 实体抽取 + 缺失字段判定（ADR-001：废弃两阶段流水线）。其输出是路由、工具调用、确认门、评测的共同契约。

## 2. Schema（v1）

```json
{
  "intent": "selection_inquiry",
  "confidence": 0.92,
  "entities": {
    "product_category": "真空泵",
    "oil_free": true,
    "pumping_speed": "100 m³/h",
    "application": "实验室"
  },
  "missing_fields": ["contact_name", "quantity"],
  "route": "selection_flow",
  "needs_clarification": true,
  "needs_human": false,
  "human_reason": null,
  "refusal_reason": null
}
```

| 字段 | 类型 | 约束 |
|---|---|---|
| `intent` | enum | 一期 13 值（§3）；映射 `unknown` 时 route 必为 `clarify` |
| `confidence` | float | 0~1；`< 0.6` 时 runtime 强制 `needs_human`（low_confidence） |
| `entities` | dict | 键为受控实体集（§4）+ adapter 扩展键（`x_*` 前缀）；值一律字符串或布尔，禁止嵌套对象 |
| `missing_fields` | list | ⊆ manifest `inquiry_sink.required_fields ∪ optional_fields`；无 inquiry_sink 时恒空 |
| `route` | enum | 一期 10 值：`product_flow / selection_flow / spec_match_flow / supplier_flow / compare_flow / inquiry_flow / knowledge_flow / handoff_flow / clarify / refuse_fabrication` |
| `needs_clarification` | bool | 与 `missing_fields`/`unknown` 意图联动，由 runtime 校验一致性 |
| `needs_human` / `human_reason` | bool / enum | reason 枚举见 port-spec §6.5 关联的站点约定（complex_selection/customization/complaint/legal/user_request/low_confidence/repeated_failure…） |
| `refusal_reason` | enum? | `pricing_disabled / lead_time_disabled / stock_disabled / content_policy`；非空时 route 必为 `refuse_fabrication`，回答走模板 |

**一致性硬校验**（runtime，失败即 fallback）：`route=refuse_fabrication ⇔ refusal_reason 非空`；`needs_human=true ⇒ human_reason 非空`；`missing_fields ⊆ manifest 字段`。

## 3. 意图枚举（v1）

```text
product_inquiry        产品咨询
spec_inquiry           参数咨询
selection_inquiry       选型咨询
price_inquiry          报价咨询
sample_request         样品咨询
lead_time_inquiry      货期咨询
stock_inquiry          现货查询
customization_request  定制需求
supplier_search        供应商寻找
certification_inquiry  认证咨询
complaint              售后/投诉
human_request          转人工
unknown                无法识别
```

意图 ↔ 路由映射在代码路由表（可测试），意图枚举变更 = 本规格版本变更 + A 族评测集同步。

映射补充：`spec_inquiry` 且实体含结构化规格参数（抽速/极限真空/无油等数值或布尔）→ `spec_match_flow`（规格匹配）；`supplier_search` / `certification_inquiry` → `supplier_flow`（供应商推荐，实体含 product_category 或 region）；点名两个产品对比 → `compare_flow`（产品对比）。

## 4. 受控实体集（Core 内置）

`product_category / product_name / model / brand / quantity / target_vacuum / pumping_speed / power / interface / material / oil_free / explosion_proof / application / delivery_time / budget / company / contact_name / contact_phone / email / region`

行业扩展实体由 adapter 声明（`x_` 前缀），Core 不感知其语义、只透传。

## 5. 失败与降级

1. 输出违反 Schema → 重试 1 次（温度=0，附错误说明）→ 仍失败 → `route=clarify`、`intent=unknown` 固定输出（确定性兜底，不裸抛）。
2. 轻量模型与强模型可分层使用（成本工程），但 Schema 与本契约不变。
3. `structured_output_version` 写入 trace；评测按版本分组回归。

## 6. 评测要求

A 族意图/实体用例直接断言本 Schema 字段；`needs_clarification`/`refusal_reason` 的一致性校验必须有专项用例（D 族）。

v1.3 · 2026-09-14 · 路由枚举补 spec_match_flow / supplier_flow / compare_flow（规格匹配+供应商推荐+产品对比激活，详见 .ai/logs）
---
*维护者：工程组 · 变更须同步路由表 + eval golden set*
