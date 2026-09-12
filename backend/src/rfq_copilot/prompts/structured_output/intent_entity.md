---
name: intent_entity_extraction
version: 1
locale: zh-CN
capability: understanding
---
# 任务

分析用户最新输入（结合对话历史），**只输出**一个符合 Schema 的 JSON 对象（05-structured-output-spec v1），不输出任何其他文字。

# 规则

1. `intent` 只能取 13 个枚举值；无法判断用 `unknown`。
2. `entities` 只收受控实体键；行业扩展键加 `x_` 前缀；值为字符串或布尔，禁止嵌套。
3. `confidence` 依据输入明确程度自评：<0.6 时 runtime 将强制转人工。
4. `missing_fields` 仅列建询盘所缺的 manifest 必填/选填字段。
5. 意图涉及被禁用能力（{{disabled_capabilities}}）时：`route="refuse_fabrication"` 且 `refusal_reason` 必填。
6. 复杂选型/大额/非标/投诉/法律/用户主动要求 → `needs_human=true` 且 `human_reason` 必填。
7. `route` 与 intent 的映射遵循路由表；不确定时用 `clarify`。

# Few-shot（见 core/eval/fewshot/，此处不展开）

按测试集口径保持稳定；不要发明新枚举值。
