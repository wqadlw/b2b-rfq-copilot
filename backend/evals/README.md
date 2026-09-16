# Evals — golden-set 回归门禁

## 这是什么

`golden/router_cases.json` 是**路由器黄金用例集**：把"某条消息应该走哪条路由 / 该不该拒答"
固化成可执行断言。来源是 LangGraph/LangSmith 官方评测实践的轻量版——
不引入云服务，用 pytest 在 CI 里捕获回归（"catch regressions before users do"）。

## 两类用例

| 类别 | 字段 | 断言对象 | LLM |
|---|---|---|---|
| `cases` | `expect.route/intent/refusal_reason` | `_understanding_from_tools`（确定性捷径） | 0 token |
| `answer_invariants` | `contains` / `absent` | 图跑完的最终 answer 文本不变量 | 0 token |

**为什么全部 0-token**：只有确定性捷径与拒答模板才允许进 CI 门禁。
任何需要真实 LLM 判断的用例都不该放这里（会把成本和外部依赖带进 CI）。
需要真实模型的端到端评测走人工流程（见 `.ai/private/live-eval-numbers.md`）。

## 怎么跑

```powershell
uv run pytest backend/tests/evals -q        # 只跑评测集
uv run pytest -m eval -q                    # 同上（marker 方式）
uv run pytest -q                            # 全量（CI 默认，含评测集）
```

## 怎么加用例

1. 往 `golden/router_cases.json` 的 `cases` 或 `answer_invariants` 追加一条，`id` 唯一
2. 当地跑 `uv run pytest backend/tests/evals -q` 确认通过（**先跑一遍确认现状行为**，
   用例记录"当前正确行为"，不是"我认为应该的行为"）
3. 若发现用例失败而现状行为确实错误 → 那是真 bug，修代码而不是改用例

## 与既有测试的分工

- `backend/tests/api/*`：HTTP 契约（游客门禁、鉴权、限流、SSE 协议）
- `backend/tests/integration/*`：图流程（interrupt/resume、持久化、RAG 隔离）
- `backend/tests/evals/*`：**路由/拒答决策的黄金集回归**（本目录）
