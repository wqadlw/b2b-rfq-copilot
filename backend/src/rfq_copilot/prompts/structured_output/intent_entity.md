---
name: intent_entity_extraction
version: 3
locale: zh-CN
capability: understanding
---
# 任务

分析用户最新输入（结合对话历史），**只输出**一个符合 Schema 的 JSON 对象（05-structured-output-spec v1），不输出任何其他文字。

# 规则

1. `intent` 只能取以下 13 个枚举值（精确拼写，禁止自造）：
   product_inquiry / spec_inquiry / selection_inquiry / price_inquiry / sample_request /
   lead_time_inquiry / stock_inquiry / customization_request / supplier_search /
   certification_inquiry / complaint / human_request / unknown
   判定指南：问参数=spec_inquiry；要推荐/找产品=product_inquiry；选型建议=selection_inquiry；问某产品归谁卖=supplier_search。
2. `entities` 只收受控实体键；行业扩展键加 `x_` 前缀；值为字符串或布尔，禁止嵌套。
3. `confidence` 依据输入明确程度自评：<0.6 时 runtime 将强制转人工。
4. `missing_fields` 仅列建询盘所缺的 manifest 必填/选填字段。
5. 意图涉及被禁用能力（{{disabled_capabilities}}）时：`route="refuse_fabrication"` 且 `refusal_reason` 必填。
6. 复杂选型/大额/非标/投诉/法律/用户主动要求 → `needs_human=true` 且 `human_reason` 必填。
7. `route` 从以下 9 个枚举值中选一，按触发条件映射（不确定时用 `clarify`）：
   - `product_flow`：要推荐/找产品（具体产品）
   - `selection_flow`：选型建议
   - `spec_match_flow`：用户给出结构化规格参数（抽速/极限真空/无油等数值或布尔）要求匹配产品
   - `supplier_flow`：找供应商/某类产品有哪些厂家/某地区有什么供应商（实体含 product_category 或 region）
   - `knowledge_flow`：知识/政策/流程问答
   - `inquiry_flow`：要创建询盘/提交需求
   - `handoff_flow`：转人工
   - `clarify`：信息不足
   - `refuse_fabrication`：仅当命中被禁用能力（按规则 5）

# Few-shot（见 core/eval/fewshot/，此处不展开）

按测试集口径保持稳定；不要发明新枚举值。
