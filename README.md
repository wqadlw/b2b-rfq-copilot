# b2b-rfq-copilot

> 密级：公开

**面向垂直行业 B2B 平台的智能询盘引擎 · RFQ Copilot**

[![CI](https://github.com/wqadlw/b2b-rfq-copilot/actions/workflows/ci.yml/badge.svg)](https://github.com/wqadlw/b2b-rfq-copilot/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)

将采购咨询连接到产品检索、知识问答与结构化询盘。通过端口、适配器和能力清单对接站点，真空工业是首个行业实例。

**当前状态：业务原型与站点适配实现持续完善中。** 已有独立聊天页、嵌入式组件和 HTTP 适配示例；不将组件存在、历史联调或测试报告等同于完整生产验收。

## 它解决什么问题

B2B 采购需求通常分散在多轮咨询中，产品参数、供应商信息和询盘提交彼此割裂。本项目围绕以下业务链路组织交互：

```text
访客表达需求 → 查询产品与知识 → 澄清需求 → 展示询盘摘要
  → 用户显式确认 → 通过适配器创建询盘 → 查询进度或引导人工跟进
```

它不是自动报价或自动成交系统。无可靠来源的价格、货期和库存不应由模型推测；站点负责真实业务数据、询盘存储及后续线索运营。

## 设计与实现

- **确定性业务编排**：LangGraph 管理理解、路由、回答与询盘确认。LLM 用于结构化理解和知识答案生成，业务代码决定调用路径，而非自主工具循环。
- **端口与适配器**：产品、供应商、知识、询盘和线索分发是基础抽象；提供内置 demo 与 HTTP 行业适配示例，另有询盘状态查询扩展。
- **Capability Manifest**：驱动基础端口装配、禁用能力拒绝策略、负向评测派生和 UI 配置。新增业务扩展的清单覆盖仍在完善。
- **询盘确认门**：使用 LangGraph `interrupt()` / `Command(resume=...)` 暂停并恢复提交流程；适配器负责对接业务写入。
- **知识检索与引用**：文档切分、embedding、检索、信任标签与来源引用；默认使用 hashing embedding、内存向量库和 Noop reranker，可配置兼容 API 的 embedding。
- **流式交互**：FastAPI POST SSE 承载正文、工具状态、引用、业务卡片和询盘事件。
- **访问与输出约束**：提供检索上下文隔离、确定性拒答、输出过滤、内部管理接口鉴权及限流机制；这些机制需要持续评测，不构成绝对安全或零编造保证。

## 功能状态

| 模块 | 当前实现 | 使用边界 |
|---|---|---|
| 产品搜索 | demo、离线目录、HTTP 适配及产品卡片 | 卡片分页是本地展示，不等于继续查询下一页 |
| 规格匹配 | 基础数值与条件匹配 | 非完整的跨单位、全库工业选型引擎 |
| 供应商 | 列表、匹配理由与供应商卡片 | 详情及不同访问路径仍需完善 |
| 产品对比 | 后端差异文本 | 当前解析限定 demo 产品编号，无前端对比矩阵 |
| 知识问答 | 检索、生成、引用；游客可走摘录路径 | 默认检索不依赖语义模型；流式完成逻辑待完善 |
| 行业方案与案例 | 离线数据检索及卡片展示 | 需另行配置数据，不是动态方案或 BOM 生成 |
| 询盘创建 | 确认、恢复、幂等与 HTTP 提交 | 前端仍有演示字段，草稿编辑到提交的接线待完善 |
| 询盘状态 | HTTP 查询与状态卡片 | demo 状态查询仍是空结果占位 |
| 运营接口 | 会话回放、统计、FAQ、知识管理、人工接管 | 没有对应前端后台；部分接线和存储仍待完善 |
| 嵌入组件 | IIFE 构建、Shadow DOM、自挂载 | 宿主布局、身份生命周期及移动端需集成验收 |

## 架构与数据边界

```text
React 聊天页 / 嵌入式 Widget
              │ POST SSE
              ▼
FastAPI App：配置、身份、运行时装配、游客快捷路径
              │
              ▼
Core：LangGraph、确定性路由、RAG、策略、评测
              │ 端口契约 + Capability Manifest
              ▼
Adapters：demo / HTTP 行业示例 / 离线目录
              │
              ▼
Site：产品、供应商、询盘存储与后续业务运营
```

目标依赖方向为 `app → core/adapters → ports`，由 import-linter 检查。部分行业扩展仍有跨层耦合，通用化边界尚需收敛。

### 持久化范围

- Graph checkpoint 支持 `memory`、`sqlite`、`postgres`，用于图状态及待确认流程恢复。
- 消息、累计槽位、FAQ、运营统计、限流和预算等仍主要保存在进程内存中。
- 默认 RAG 使用内存向量库；pgvector 组件及独立验收脚本存在，但尚未接入默认 runtime。
- demo 询盘是内存数据；HTTP 适配模式由站点负责业务持久化。

**启用 PostgreSQL checkpoint 不等于服务整体具备多实例共享状态或完整重启恢复能力。**

## 快速开始

### 环境要求

- Python 3.12+ 与 [uv](https://docs.astral.sh/uv/)
- Node.js 22 与 pnpm 11（与当前 CI 保持一致）
- 用于完整模型问答的 OpenAI 兼容 LLM 服务

### 本地开发

```bash
git clone https://github.com/wqadlw/b2b-rfq-copilot.git
cd b2b-rfq-copilot
uv sync --locked --extra dev
```

将 `.env.example` 复制为 `.env`，设置 `LLM_BASE_URL`、`LLM_API_KEY` 和 `LLM_MODEL`。首次运行使用 `ADAPTER=demo`，保持 `KNOWLEDGE_DATA_DIR` 为空，以免混入站点私有数据。不要提交 `.env`。

启动后端：

```bash
uv run uvicorn rfq_copilot.app.main:app --host 127.0.0.1 --port 8000
```

另开终端，在仓库根目录启动前端：

```bash
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend dev
```

访问 `http://localhost:5173`。默认 demo 仍会在需要模型的路径调用 LLM，不是所有问题都能无 Key 离线回答。游客零 LLM 路径需通过 `GUEST_TIER_ENABLED` 配置启用。

### Docker Compose

准备 `.env` 后运行：

```bash
docker compose up --build
```

默认启动前后端。以下命令额外启动 PostgreSQL + pgvector：

```bash
docker compose --profile prod up --build
```

`prod` profile 不会自动切换应用的 checkpoint 或 RAG 后端。Compose 当前是演示模板，生产环境需要单独处理数据库配置、持久卷、身份、访问范围、监控及备份恢复。

## 嵌入式 Widget

```bash
pnpm --dir frontend build:widget
```

产物为 `frontend/dist-widget/rfq-chat.js`，包含 React 和注入 Shadow DOM 的样式，宿主无需另装 React。部署到自己的静态资源服务后，在宿主页加载：

```html
<div id="rfq-copilot-widget" style="height: 640px;"></div>
<script src="/assets/rfq-chat.js" data-endpoint=""></script>
```

`/assets/rfq-chat.js` 是示例部署路径，不是仓库自动提供的路由。`data-endpoint` 为空表示 API 同源；跨域时需配置实际后端地址并完成访问策略配置。

组件不自带完整浮窗壳、通用 mount/unmount API 或移动键盘避让。登录票据在创建会话后的持续传递与刷新仍需完善，不能直接将演示登录交互用于真实用户接入。普通前端 Docker 构建也不会自动发布 widget 产物。

## 测试与评测

### 本地检查

在独立测试配置下运行；应用测试可能加载当前目录 `.env`，请勿继承生产 API、私有知识目录或生产数据库配置。

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run lint-imports
uv run pytest -q
uv run python scripts/check_repo_policy.py
pnpm --dir frontend lint
pnpm --dir frontend test
pnpm --dir frontend build
pnpm --dir frontend build:widget
```

当前 CI 包含后端 lint、类型检查、pytest、导入契约、前端 lint/build、仓库政策扫描和独立 pgvector 验收。前端 Vitest 与 widget 构建尚未纳入 CI。

### 评测口径

| 入口 | 实际范围 |
|---|---|
| `uv run pytest -m eval -q` | FakeLLM + demo 的确定性回归，执行派生 B 族及标记为 CI 的部分 D 族 |
| `uv run python scripts/run_eval.py` | 加载用例并实跑派生 B 族；不是完整 A/B/C/D 回归 |
| `uv run python scripts/run_eval.py --live` | 调用真实模型运行 JSONL 用例；产生费用，当前不包含派生 B 族 |

**报告限制：** baseline 当前会把未执行的 A/C/D 显示为通过，且 B 断言失败未接入失败退出码；live 的多轮驱动、隔离及指标覆盖也仍待完善。因此暂不发布全族通过率、意图准确率、P95 或成本承诺。历史产物见 [eval/reports/](eval/reports/)，应结合运行模式和驱动器版本解读。

真实模型评测应明确使用 `ADAPTER=demo`、非私有知识和独立测试配置，避免调用真实业务写端口。确定性测试通过不等于真实模型或站点全链路验收通过。

## 当前完善重点

1. 贯通产品 ID、真实联系方式采集、草稿编辑、重新确认与提交结果展示。
2. 完成嵌入身份生命周期及 SSE 的完成、中止、重连和去重处理。
3. 补齐 FAQ 更新、预算扣减、人工接管和反馈记录的业务接线。
4. 修正评测报告口径，增加前后端交互与真实部署条件下的验收。
5. 收敛 manifest 与端口边界，再完善持久化、可观测性和生产部署。

## 文档与参考

| 文档 | 内容 |
|---|---|
| [架构总览](docs/ARCHITECTURE.md) | 三层设计与模块边界 |
| [端口规范](docs/specs/01-port-spec.md) | 端口、manifest、装配与派生契约 |
| [API 规范](docs/specs/03-api-spec.md) | 会话与 SSE 契约 |
| [评测规范](docs/specs/06-eval-spec.md) | 评测族、断言与目标门禁 |
| [代码组织](docs/CODE_ORGANIZATION.md) | 目录、依赖与工程约定 |
| [前端风格](docs/FRONTEND_STYLE_GUIDE.md) | 视觉与交互设计目标 |
| [技术决策](docs/adr/) | ADR 记录 |
| [参考项目](docs/REFERENCES.md) | 借鉴来源与合规边界 |
| [仓库政策](docs/policies/repo-policy.md) | 公开内容与敏感信息边界 |

规范包含尚未完整落地的目标；功能状态以当前实现与可复现验证为准。本项目使用 FastAPI、LangGraph、Pydantic、React 等开源组件，相关借鉴说明见参考文档。

## License

[MIT](LICENSE)
