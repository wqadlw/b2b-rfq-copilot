# ADR-0009：场景类追问改道知识库 + 检索查询实体补写

- 状态：Accepted
- 日期：2026-09-20
- 关联：ADR-0008（选型问法护栏 / 回答历史注入）；05-structured-output-spec v1；03-api-spec

## 背景（实测）

多轮会话：user「什么是罗茨泵？」→ assistant（知识回答）→ user「它适合什么场景？」。

意图 LLM 已正确借助历史解析「它」＝罗茨泵，判定 intent=selection_inquiry → route=selection_flow。
selection_flow 无规格数据时落入 answer 节点 catch-all，输出
「请补充更多信息，例如目标真空度、抽速、应用场景…」——用户问的是知识（应用场景），
却收到要规格的反问，体感"不聪明"。

业界锚点（Nemorize 2026 RAG Roadmap / AI Search 多轮实践）：
**Retrieve-Then-Ask**——低风险模糊问题应先检索作答、答末再提供精修路径；
多轮指代经历史解析后应进入检索改写（query rewriting），而非原样透传向量检索。

## 决策

### D4 场景追问护栏（scenario_over_clarify）

routing_guards 家族第四个确定性护栏（沿用 D1 selection_over_search 的形态）：

- 触发条件（全部满足）：
  1. `route == "selection_flow"`（唯一易落"补工况"兜底的对话型路由）；
  2. 消息命中场景类标记词（适合什么 / 什么场景 / 应用场景 / 用在哪 / 用在什么 /
     哪个行业 / 什么行业 / 适用范围 / 哪些场合）；
  3. 会话历史非空，且历史中出现产品语境词（「泵」「机组」）——证明"它"有指代对象。
- 动作：改道 `knowledge_flow`，写入 `route_guard="scenario_over_clarify"`、
  `route_guard_from`（审计轨迹），understand 节点推「正在整理回答」状态。
- 明确不改：product_flow / compare_flow / spec_match_flow 不受影响；
  首轮场景问题（无历史）不改——意图分类器自行判断，多为 selection 合法场景。

### D5 检索查询实体补写（query enrichment）

knowledge_flow 检索原样用 `message`（"它适合什么场景？"）做向量检索——指代词
零语义，召回必差。改为复用 `select_search_keyword`（B5 后已支持实体头二字放宽）：

- 若其返回值 ≠ 原消息（即从 understanding 抽到了品类实体），检索查询改为
  `f"{message} {keyword}"`（问题 + 解析出的品类词，如 "它适合什么场景？ 罗茨泵"）；
- 否则维持原消息。回答层【问题】仍用原消息，不影响引用与白名单逻辑。

## 后果

- 正收益：场景类追问获得知识库直接回答（Retrieve-Then-Ask）；指代追问检索召回提升。
- 代价：selection_flow 的"补工况"引导在场景问法上不再出现（该引导对真规格诉求保留）。
- 风险与缓解：历史含「泵/机组」即放行可能过宽——但本站为真空设备垂直域，
  历史几乎必为产品语境；知识库 no-answer 路径（承认覆盖不足 + 两路径）兜底。

## 门禁

pytest（新增护栏/改写回归测试）· ruff · ruff format · mypy · run_eval（B/C/D 家族全绿才合入）。
