# eval/ — 评测用例与运行器

## 两个运行器，一份用例

| 运行器 | 用途 | 依赖 | 何时跑 |
|---|---|---|---|
| `uv run pytest -m eval -q`（`backend/tests/evals/`） | **CI 门禁**：确定性用例回归（0 LLM token、无网络） | 无 | 每次提交（CI 自动） |
| `uv run python scripts/run_eval.py --live` | **人工评测**：全族用例打真实模型/RAG + 忠实度评审 | `LLM_API_KEY`、可选 bge-m3 | 模型/提示词变更后人工执行 |

两个运行器共用同一套断言语义：`rfq_copilot.core.eval.assertions`。

## 用例家族

| 族 | 目录 | 内容 | CI |
|---|---|---|---|
| A | `cases/A_positive/` | 正向问答/搜索/选型 | ✗（需 LLM） |
| B | 派生（`core/eval/deriver.py`） | 编造攻击（对禁用能力） | ✓ 全部 |
| C | `cases/C_poisoning/` | 投毒资料隔离 | ✗（需检索+LLM） |
| D | `cases/D_permission/` | 越权/确认门/询盘路由 | ✓ 标 `ci: true` 者 |

## `"ci": true` 约定

只有确定性可判的用例才允许标 `ci`：消息必须命中确定性捷径（拒答词表 / 询盘关键词 /
空寒暄），断言只看可用证据（模板话术、事件流、工具调用、询盘记录）。
标了 `ci` 但实际需要模型的用例会在 CI 里以 `FakeLLM exhausted` 明确失败——
这是刻意设计：宁可在 CI 里报"这条不该进 CI"，也不要让门禁变成摆设。

多轮/交互类用例（确认卡 resume、幂等重放）保持 `ci` 不标，走 `--live`。

## 断言语义（`core/eval/assertions.py`）

`tool_called` / `tool_not_called` / `port_not_called` / `template_match` /
`no_price_pattern`(支持 `except_whitelist`) / `sse_event_sequence` / `citation_present` /
`no_action_from_context` / `no_system_prompt_leak` / `db_state` / `json_schema`。

**未实现的断言类型会抛错**（历史缺陷：`tool_called`/`port_not_called`/`citation_present`/
`db_state` 四类共 38 处断言此前静默通过，包括"未确认不得写询盘"这条安全守卫）。

## 加用例

1. 追加到对应族的 `.jsonl`（一行一 JSON，字段：`id`/`family`/`turns`/`asserts`，
   可选 `preconditions`/`resume_action`/`note`/`ci`）
2. 先跑一次确认它**记录的是当前正确行为**（不是"你认为应该的行为"）
3. 失败且现状确实错误 → 修代码，不改用例
