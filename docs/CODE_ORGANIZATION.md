# CODE ORGANIZATION · 代码组织与工程分层规范

> 密级：公开 · 版本 v1.0 · 2026-09-12 · **宪法级三件套之二**（PROJECT.md 定位 / 本文档代码组织 / policies/repo-policy.md 边界）
> 依赖与目录规则的**唯一权威源**——其他文档只引用不复述。与任何文档冲突时以本文档为准。

## 1. 总原则

1. Monorepo，逻辑严格分层；Core 不依赖任何站点、任何行业，只依赖 Ports。
2. Adapters 实现 Ports；App 负责组装，不含业务规则；前端只消费 API，不含业务判断。
3. 所有边界数据必须过 Pydantic Schema；禁止裸 dict 跨层传递。
4. 所有配置显式化（环境变量 + manifest + 版本化 Prompt），禁止隐式魔法值。
5. 所有外部调用必须有超时、结构化日志、错误处理（异常只用 port-spec §8 体系）。
6. 站点私有实现、真实数据、密钥永不进入公开仓库（详见 repo-policy）。
7. Prompt、Manifest、Schema、评测用例全部版本化。
8. 禁止裸 `print`；禁止 `except:` 裸捕获；日志禁明文 PII。
9. 依赖新增必须在 PR 说明理由并过 import-linter 契约。

## 2. 仓库结构（唯一权威树）

```text
b2b-rfq-copilot/
├── README.md · LICENSE · pyproject.toml · Makefile · docker-compose.yml · .env.example
├── docs/                        # 公开工程文档（索引见 docs/README.md）
│   ├── CODE_ORGANIZATION.md（本文） · ARCHITECTURE.md · FRONTEND_STYLE_GUIDE.md
│   ├── specs/（01 port · 03 api · 04 prompt · 05 structured-output · 06 eval · 07 security）
│   ├── adr/                     # 公开 ADR（精选双轨制，见 §12）
│   ├── guides/                  # adapter-guide · deployment（M0/M1）
│   └── policies/repo-policy.md
├── backend/
│   ├── src/rfq_copilot/         # src layout（可安装包，防误引未装代码）
│   │   ├── ports/               # 5 端口 Protocol + Pydantic Schema + errors.py
│   │   ├── core/                # 通用引擎（agent/rag/policies/routing/memory/streaming/eval）
│   │   ├── adapters/            # demo/ · vacuum_b2b_sample/（各含 manifest.yaml）
│   │   ├── prompts/             # 提示词资源（包内数据，frontmatter 版本化）
│   │   ├── app/                 # FastAPI 组装层（main/api/dependencies/runtime/middleware）
│   │   ├── schemas/             # API 层模型（chat/inquiry/events/…）
│   │   ├── observability/       # logging/tracing/metrics/audit
│   │   └── config/              # pydantic-settings 配置对象
│   ├── tests/                   # unit/ · integration/ · api/ · fixtures/
│   └── pyproject.toml（继承根）
├── frontend/                    # React 19 + TS + Vite + Tailwind v4 + shadcn/ui
│   └── src/{app,components,hooks,lib,styles}   # 组件分类见 FRONTEND_STYLE_GUIDE §12
├── eval/                        # 评测数据与产物（代码在包内 rfq_copilot/eval/）
│   ├── cases/（A_positive · B_fabrication · C_poisoning · D_permission）
│   ├── datasets/ · generated/ · reports/
├── scripts/                     # bootstrap / ingest_demo_knowledge / run_eval / check_repo_policy
└── .github/                     # workflows · ISSUE_TEMPLATE · PULL_REQUEST_TEMPLATE
```

说明：`PROJECT.md`（章程）在仓库根，不入 docs/；`backend/manifests/`、顶层 `core/ ports/` 等**作废**——manifest 与 adapter 同包共置（§5.2），目录以本树为准。

## 3. 依赖方向契约（import-linter 强制）

```text
允许：app → core · app → adapters · core → ports · adapters → ports
禁止：core → adapters · ports → core · ports → adapters · adapters → core · frontend → backend 内部实现
```

- CI 用 **import-linter** 固化上述契约（contracts 写入根 pyproject.toml），违规即红。
- 最低人工红线：`ports` 与 `core` 的源码中不得出现字符串 `rfq_copilot.adapters`；`ports` 不得出现 `rfq_copilot.core`。
- adapter 需要(core 才有的)能力时，**把该能力下沉为 ports 的 Schema/错误定义**，而不是开洞——这是本架构最重要的纪律。

## 4. 分层职责细则

### 4.1 ports/
定义抽象端口 + 输入输出 Schema + `errors.py`（CopilotError 树，权威：port-spec §8）。不含业务逻辑，不依赖 core/adapters/app，不引用数据库模型或 HTTP 框架。端口签名以 `docs/specs/01-port-spec.md` §3 为唯一权威。

### 4.2 core/
通用引擎：`agent/`（graph/state/nodes/structured_output/tool_registry）· `rag/`（chunking/embedding/retriever/reranker/trust/citation）· `policies/`（refusal/pricing/lead_time/anti_abuse/poisoning_defense）· `routing/`（deterministic_router）· `memory/` · `streaming/` · `eval/`（runner/metrics/assertions/generators/report）。
铁律：不 import adapters；不 import FastAPI；不直连数据库（向量/检查点经端口式适配注入）；不读站点环境变量；不写死任何站点/行业名。

### 4.3 adapters/
实现端口，负责协议转换（HTTP/Mock/文件）。`demo/` 内置模拟数据与种子脚本；`vacuum_b2b_sample/` 为脱敏示例（example 域名、placeholder token）。
铁律：只依赖 ports；不修改 core 策略；不夹带站点私有细节（脱敏审查过 CI repo-policy check）。真实站点适配器在私有站点仓库，不入公开库。

### 4.4 app/
组装 runtime：加载 manifest（V1~V7 校验）→ 注入 adapter → 构建 Agent 图 → 暴露 API（权威：03-api-spec）。
铁律：不写业务判断；不写 Prompt 文本；不绕过 core 直接调端口做业务。

### 4.5 schemas/
API 层 Pydantic 模型（chat/inquiry/product/supplier/knowledge/events/eval）。前端 `frontend/src/lib/types.ts` 与之对齐（脚本生成或 CI 校验）。端口 Schema 定义在 ports 内（不是这里）——schemas/ 只承载 HTTP 形状。

### 4.6 observability/
logging（structlog JSON）/ tracing（Langfuse）/ metrics / audit。规则：所有工具调用与模型调用有 trace（token/latency/model）；所有检索记录 retrieved_docs；PII 一律掩码（权威：07-security-spec §5~6）。

## 5. 配置、Manifest 与 Prompt

### 5.1 环境变量
只走 `.env`（仅提交 `.env.example`），经 **pydantic-settings** 加载为类型安全配置对象；分组前缀：`LLM_* / EMBEDDING_* / RERANK_* / DATABASE_URL / LANGFUSE_* / APP_*`。真实密钥不入任何文件（repo-policy §2）。

### 5.2 Manifest
**与 adapter 同包共置**：`rfq_copilot/adapters/<name>/manifest.yaml`——manifest 是 adapter 的自描述，不是全局配置。runtime 启动加载并过 V1~V7 校验；变更有评测派生联动（06-eval-spec §6）。

### 5.3 Prompts
**包内资源**：`backend/src/rfq_copilot/prompts/{system,structured_output,answer,refusal,security}/`。每个文件带 YAML frontmatter（`name/version/locale/capability`），版本写入 trace（权威：04-prompt-spec §1）。模板变量注入，禁止真实站点名。收进包内的理由：版本随 git 与发布走，评测可按 `prompt_version` 精确回归。

## 6. 命名规范

```text
文件/模块 snake_case · 类 PascalCase · 函数 snake_case · 常量 UPPER_SNAKE_CASE · 测试 test_*.py
端口：ProductCatalogPort / SupplierDirectoryPort / KnowledgeSourcePort / InquirySinkPort / LeadDistributionPort
适配器类：<Name><Port>Adapter（如 DemoProductCatalogAdapter / VacuumSampleInquirySinkAdapter）
异常：以 port-spec §8 体系为权威（CopilotError → ConfigError/PortError/PolicyError/RateLimitError）
前端组件 PascalCase.tsx · hooks useXxx.ts（视觉与组件命名权威：FRONTEND_STYLE_GUIDE）
```

## 7. 测试组织

```text
backend/tests/unit/{core,ports,adapters,eval} · integration/ · api/ · fixtures/
```

最低测试集（M0 必须全绿的 7 条）：①manifest 禁用能力后工具不注册 ②禁用能力后拒绝策略生成 ③价格编造攻击被拒 ④货期编造攻击被拒 ⑤商户内容指令不执行 ⑥建询盘必须经确认门 ⑦SSE 事件顺序正确。
评测数据与报告在顶层 `eval/`；评测**代码**在包内 `rfq_copilot/eval/`；四族（A/B/C/D）为权威（06-eval-spec），不增设 E/F 族。

## 8. 日志与审计

- structlog JSON 结构化；必备字段：`trace_id/session_id/request_id/intent/route/tool_name/latency_ms/status/error_code`。
- 脱敏：手机号 `138****0000`、邮箱 `z***@example.com`；密钥与 PII 明文永不入日志（07-security-spec §5）。
- 写操作双审计：adapter 本地审计记录 + 站点侧审计（如站点 OperationLog）。

## 9. 分支与提交

- **Conventional Commits**：`feat(core): … / fix(api): … / feat(adapters/demo): … / test(eval): … / docs: … / chore: …`。
- **分支双轨**：内部席位 `ai/<agent>/<task>`（如 `ai/glm/m0-skeleton`，对应 TASK_BOARD 任务 ID）；外部贡献者 `feat/… fix/… docs/… eval/… chore/…`。PR 描述必须链接任务 ID 或 issue。
- 禁 `git add -A`；禁 force push 主分支；人类/维护者合并。

## 10. CI 质量门（GitHub Actions）

1. ruff（lint+format check）2. mypy（strict）3. pytest（unit/integration/api）4. import-linter 契约 5. 前端 build + lint 6. **check_repo_policy**（扫 `.env`/token 模式/真实域名/真实手机号邮箱/私有站点路径/未脱敏字段映射——规则与 `scripts/check_repo_policy.py` 同源）7. Docker build。
评测门禁（B/C/D 100%）随 pytest 运行（06-eval-spec §1）；`@eval_live` 用例每日调度不阻塞 PR。

## 11. 公开/私有边界

权威源：`docs/policies/repo-policy.md`。速记：公开仓库 = 通用引擎 + demo + 脱敏 vacuum_b2b_sample + 评测框架 + docs/；私有 = 真实站点适配、内部 API、真实字段映射、业务数据、`.ai/` 内部治理（ADR-007）。

## 12. 文档与 ADR 双轨制

- **权威源表**：代码组织=本文 · 端口/Schema/装配=01-port-spec · API=03-api-spec · 提示词=04-prompt-spec · 结构化输出=05 · 评测=06 · 安全=07 · 视觉=FRONTEND_STYLE_GUIDE · 边界=repo-policy。跨文档只引用不复述。
- **ADR 双轨**：内部权威档案 `.ai/03-DECISIONS.md`（含完整背景与评审过程，不公开）；公开 `docs/adr/` 收录**工程内容精选**（NNNN-slug.md：背景/决策/备选/后果，中文），标注对应内部编号。结构性 ADR（monorepo、ports+manifest、pgvector、SSE、frontend 栈）于 M0 播种；其余 M5 发布前补齐。
- 归并说明：UI_COPY_GUIDE 已并入 04-prompt-spec §3；DATA_PRIVACY 已并入 07-security-spec §5；OBSERVABILITY_SPEC 于 M1 随 Langfuse 集成出稿；不单独设 MANIFEST_SCHEMA.md（01-port-spec §2 即权威）。

---
*维护者：工程组 · 本文档修订须 CHANGELOG 登记 + import-linter 契约同步*
