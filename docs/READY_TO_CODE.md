# READY TO CODE · 开工门禁清单

> 密级：公开 · 版本 v1.0 · 2026-09-12 · **门禁规则：第 1~5 节全勾才进入 M1 功能开发；第 6~8 节随 M0 首个 commit 交付（不阻塞规格冻结，阻塞 M1）**
> 状态图例：✅ 已冻结/已交付 · ⏳ 随 M0 首个 commit 交付

## 1. 技术冻结

- [x] Python / Node / 包管理 / Lint / 测试 / CI 全部冻结（`adr/0001-tech-stack-freeze.md`）
- [x] 后端框架、向量方案、Embedding/Rerank/LLM 接口冻结（同上 + 01-port-spec）
- [x] 前端框架、组件库、图标库冻结（ADR-008 + FRONTEND_STYLE_GUIDE）

## 2. 契约冻结

- [x] 公开 AI API + SSE 十事件载荷（`specs/03-api-spec.md`）
- [x] 错误码体系（port-spec §8，扁平三键结构）
- [x] 站点内部 API 契约（内部规格 02 §2/§8，含价格返回时机/游客校验/去重规则）
- [x] ai_extract 字段冻结（port-spec §3.4）
- [x] 结构化输出 Schema（`specs/05-structured-output-spec.md`，含一致性硬校验）

## 3. 数据与知识

- [x] Demo 数据规格冻结（`../eval/datasets/README.md`：有价/无价/缺参/投毒样本覆盖）
- [ ] ⏳ Demo 数据文件 + bootstrap 脚本（M0）
- [ ] ⏳ 知识文档样例 20 篇 + 投毒样本 3 篇（M0 随 demo adapter）

## 4. Prompt 基线

- [x] 八个基线模板（`backend/src/rfq_copilot/prompts/`，frontmatter 版本化）：system/base · system/security · structured_output/intent_entity · answer/citation_required · refusal/pricing_disabled · refusal/lead_time_disabled · confirmation/inquiry_confirm · handoff/human_transfer
- [x] 话术规范与行为不变量（`specs/04-prompt-spec.md`）

## 5. 评测基线

- [x] 种子用例 47 条（`../eval/cases/`：A 正向 30 · C 投毒 12 · D 权限确认 15；B 族按派生器生成不手写）
- [x] 指标定义 / 通过失败判定 / 报告格式 / 命名规则（`specs/06-eval-spec.md`）

## 6. 开发环境（M0）——✅ 已交付（commit 30748e4）

- [x] docker-compose.yml（backend/frontend 默认 + `--profile prod` postgres+pgvector）
- [x] .env.example（分组键名，无值）
- [x] Makefile（help/bootstrap/dev/lint/typecheck/test/build/policy/eval + frontend 分目标）
- [x] scripts/bootstrap.py · check_repo_policy.py · run_eval.py · ingest_demo_knowledge.py（可被 CI 调用，已本地实测）
- [ ] ⏳ guides/deployment.md（M1 随文档循环补）

## 7. 安全基线

- [x] 威胁模型 8 条 + 对策挂钩（`specs/07-security-spec.md`）
- [x] 信任分级/指令隔离/确认门（port-spec §6 权威）
- [x] 限流/密钥管理/日志脱敏/PII 规则（07-security-spec §3~5）
- [x] 四个攻击场景有用例（C 族 12 条覆盖：商户内容推荐本店/忽略指令/伪造价格表/泄露系统提示/用户注入/角色扮演越权等）

## 8. 仓库治理（M0）——✅ 已交付（commit 30748e4）

- [x] LICENSE（MIT）/ README 种子 / CODE_ORGANIZATION / REPO_POLICY / REFERENCES
- [x] .github/workflows/ci.yml（七门）+ PULL_REQUEST_TEMPLATE + ISSUE_TEMPLATE
- [x] 公开 ADR：0001 技术栈冻结 · 0002 端口+manifest · 0003 pgvector · 0004 前端栈与嵌入组件

## 门禁结论

- **规格冻结项（1~5 节）：已全部达成，2026-09-12。**
- **工程地基（6/8 节）：已交付并本地验证（ruff/mypy/pytest 23/import-linter/pnpm build/eslint/四脚本/compose config 全绿）。**
- 待 push 至 GitHub 远端后由 Actions 出 CI 七门全绿证明 → 过八项 M1 前复核 → M1。
