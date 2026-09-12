# 07 · SECURITY SPEC · 安全规范

> 密级：公开 · 版本 v1.0 · 2026-09-12 · 信任分级与检索投毒防御的**权威源**是 `01-port-spec.md` §6，本文不重复其规则，只定义其余安全面。

## 1. 威胁模型

| # | 威胁 | 载体 | 对策（权威出处） |
|---|---|---|---|
| T1 | 用户 prompt injection | 聊天输入 | 指令层级 + 输出过滤（port-spec §6）+ 敏感意图限流 |
| T2 | 检索投毒 | 商户提交内容进 RAG | 信任三级 + 隔离块 + 资料指令不执行（port-spec §6） |
| T3 | 写操作滥用 | 伪造确认 / 重放 | 确认门 + `idempotency_key` 幂等 + 站点侧独立校验（双层防御） |
| T4 | 成本攻击（DoS） | 高频长会话 | §4 限流 + 会话 token 预算 + 单答 max_tokens |
| T5 | 数据外泄 | 系统提示词/内部接口/他用户数据 | 输出过滤 + 最小字段端口 + 不泄露不变量（prompt-spec §2.6） |
| T6 | PII 泄露 | 联系方式进日志/trace | §5 脱敏 |
| T7 | 供应链 | 依赖投毒 | 依赖锁定（lockfile）+ 依赖新增登记（01-CONVENTIONS 承接）+ Dependabot |
| T8 | 密钥泄露 | 仓库/日志/trace | §3 密钥管理 + CI 扫描 |

## 2. 输入安全

- 聊天输入长度上限（默认 2000 字符）；超长截断并提示。
- 控制字符/零宽字符清洗后再入上下文。
- 输入不直接拼接进系统提示词；仅作为会话层用户消息（结构隔离）。

## 3. 密钥管理

- 一切密钥只走环境变量（`.env`，仅提交 `.env.example`）；任何代码/测试/文档/评测报告/commit message 出现可用凭据字面量 = 最高红线。
- CI 双扫描：密钥模式（正则族）+ 禁入词（真实域名/公司名/表结构特征）。
- LLM/Embedding/Rerank Key 分离，最小权限；轮换流程写入 `guides/deployment.md`。

## 4. 限流与成本护栏

| 层 | 措施 |
|---|---|
| 会话 | 20 轮/小时；单会话 token 预算（默认 200k） |
| IP | 60 轮/小时；无令牌 10 轮/小时 |
| 模型调用 | 单答 max_tokens 上限；工具调用次数上限（默认 6 次/轮）；检索 top_k 上限 |
| 上游端口 | 超时（默认 5s）+ 熔断（连续失败降级模板应答） |
| 高危意图 | `complaint/legal/human_request` 不做成本优化降级，保证应答质量 |

## 5. PII 与数据留存

| 数据 | 处理 |
|---|---|
| 联系方式（phone/email） | **不进** trace 明文：日志与 Langfuse 中手机号 `138****0000`、邮箱 `z***@***.com` 掩码；询盘内文经站点侧策略存储（站点负责） |
| 会话内容 | demo 形态仅本地；prod 形态按部署方配置留存期（默认 90 天）后清理 |
| `user_ref` | 伪标识（站点签发），AI 服务不存原始账号体系 |
| 评测数据 | golden set 禁用真实用户数据；bad case 脱敏后方可入集 |

## 6. 审计

- 一切写操作（询盘创建/线索提交）在 adapter 侧留本地审计记录（who: session/when/what: draft 摘要/确认轮次），站点侧写审计日志（如 OperationLog）。
- trace 记录 `prompt_version / structured_output_version / manifest hash / tool_calls / token / cost / latency`，支撑安全事件回溯。
- 安全事件响应：GitHub Private Vulnerability Reporting（渠道见 repo-policy）。

## 7. 验收挂钩

- 本规范 §1~§5 每条对策在 `06-eval-spec.md` C/D 族或单测中至少 1 个断言。
- `scripts/security_scan.py` 为发布门禁（SOP-5）。

---
*维护者：工程组 · 安全语义变更须 ADR + 人类批准（01-CONVENTIONS §三.5）*
