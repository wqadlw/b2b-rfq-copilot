<div align="center">

# b2b-rfq-copilot

**通用垂直行业 B2B 智能询盘引擎 · RFQ Copilot**

*站在 LangGraph、pgvector、RAGFlow、ragas 等巨人的肩膀上，用诚实的借鉴与严谨的工程实践，锻造一个在安全设计上完全自研的垂直行业 B2B 智能询盘引擎。*

[![CI](https://github.com/wqadlw/b2b-rfq-copilot/actions/workflows/ci.yml/badge.svg)](https://github.com/wqadlw/b2b-rfq-copilot/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)

**状态**：🚧 活跃开发中（M4 闭环完成 · M5 发布阶段） · [评测报告](eval/reports/) · [架构文档](docs/ARCHITECTURE.md)

</div>

---

## 它解决什么问题

B2B 平台的访客咨询散落在浏览行为里，转化依赖人工客服。本引擎把咨询变成**结构化询盘**：

```
访客对话 → 意图理解 → 检索产品与知识 → 澄清缺失字段 → 用户确认 → 询盘落库 → 高价值线索分发
```

它不是一个聊天机器人，而是一条**可审计、可评测、可防御、能变现**的询盘生产线。真空工业 B2B 平台（找真空）是第一个落地实例。

## 核心特性

### 🔌 端口/适配器 + 能力清单（架构核心）

- **5 个端口**抽象引擎与站点：产品目录 / 供应商 / 知识库 / 询盘 / 线索分发——新行业接入只需实现一个 adapter 包
- **Capability Manifest**：站点用 YAML 声明自己有什么能力。没有的能力（如公开报价）→ 工具**物理不注册**进 LLM 工具列表 + 拒绝话术自动注入 + **负向评测用例自动生成**
- UI 配置由后端从 manifest 渲染下发——manifest 是工具装配、拒绝策略、评测派生、前端展示的唯一事实源

### 🛡️ 安全设计（完全自研，本项目护城河）

| 机制 | 说明 |
|---|---|
| **检索投毒防御** | 商户提交内容按不可信处理：platform/merchant/ugc 三级信任 + XML 物理隔离 + HTML 转义防伪造 + 输出过滤 |
| **拒绝编造** | 无数据源能力（价格区间/货期/库存）确定性模板作答——AI 永不编造；页面标价仅可逐字引用 |
| **写操作确认门** | 建询盘/入线索必须用户对话内显式确认，基于 LangGraph `interrupt()/Command(resume)` 实现 |
| **线索晋升防火墙** | AI 只产候选（未上架），上架与扣费永远是人工作业 |

> 检索投毒防御是 2024 年才兴起的新兴领域，工程实践极少；拒绝编造需要与 B2B 业务场景深度绑定。这三套安全设计在 GitHub 上**没有可直接借鉴的同类项目**——详见[借鉴图谱](docs/REFERENCES.md)。

### 🏭 生产工程

- **SSE 流式** 十事件契约（状态/工具调用/引用增量/确认卡/交接）+ 反代防缓冲
- **评测体系**：47 条手写种子 + B 族自动派生，程序化断言（非 LLM 主观打分），CI 内全量回归
- **可观测**：结构化日志全链路（理解→检索→重排→生成→确认），Langfuse 就绪
- **成本工程**：分层模型（轻量理解+强模型回答）、会话 token 预算、双层限流

## 架构一瞥

```text
Core（通用引擎）──依赖──▶ 5 Ports + Capability Manifest
   ▲
Adapters（demo 内置模拟数据 · vacuum_b2b_sample 真实行业示例）
   ▲
Your Site（/internal-api/* · 询盘落库 · 线索分发）
```

前端浮窗为**可嵌入设计**：宿主站点一行 `<script>` 标签接入，零 React 依赖、零样式污染。

## 快速开始（目标 10 分钟）

```bash
git clone https://github.com/wqadlw/b2b-rfq-copilot.git
cd b2b-rfq-copilot
cp .env.example .env              # 填 1 个 OpenAI 兼容 LLM Key（DeepSeek/Qwen/GLM 均可）
uv sync --extra dev               # 或 pip install -e ".[dev]"
uv run uvicorn rfq_copilot.app.main:app --port 8000
# 另开终端：cd frontend && pnpm install && pnpm dev
# 打开 http://localhost:5173 即可对话
```

> Docker Compose 形态（`--profile prod` 含 pgvector）见 [docs/guides/deployment.md](docs/guides/deployment.md)。

## 评测数字（真实 LLM 实测 · deepseek-flash）

| 族 | 用例 | 通过率 | 说明 |
|---|---|---|---|
| A 意图/实体 | 30 | **90%** | 27/30 通过；3 例意图边界（对比/多约束选型） |
| A Faithfulness | 26/30 | **87%** | ragas 思想裁判：回答是否忠实于上下文 |
| C 投毒防御 | 12 | **92%** | 11/12；唯一失败为驱动器语义适配项 |
| B 编造攻击 | 15 | **100%** | manifest 自动派生 + 确定性拒绝路径 |
| D 权限确认 | 15 | pytest **100%** | interrupt/resume/幂等/取消 全过；e2e 驱动器适配中 |

> 检索当前为词法降级模式；接入 bge-m3 后的 Recall/Relevancy 将随后更新。程序化断言（B/C/D 族）不依赖 LLM 主观打分。

## 文档

| 文档 | 内容 |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 三层架构总览 |
| [docs/specs/01-port-spec.md](docs/specs/01-port-spec.md) | 端口/manifest/装配/派生（唯一权威） |
| [docs/REFERENCES.md](docs/REFERENCES.md) | **借鉴图谱**：借了什么/学到什么程度/落在哪个文件/合规边界 |
| [docs/FRONTEND_STYLE_GUIDE.md](docs/FRONTEND_STYLE_GUIDE.md) | 视觉规范（Industrial AI Clean） |
| [docs/specs/06-eval-spec.md](docs/specs/06-eval-spec.md) | 评测体系与自动派生规则 |
| [docs/adr/](docs/adr/) | 关键技术决策（技术栈冻结/pgvector/前端栈） |

## 借鉴与自研

架构思想站在巨人肩上——**LangGraph** 的状态机与 interrupt/resume、**RAGFlow** 的分块与引用溯源、**ragas** 的评测指标思想、**pgvector + BGE** 的存储与检索、**Vercel AI Chatbot / assistant-ui** 的前端形态。

核心差异化**完全自研**：检索投毒防御体系、能力清单驱动的拒绝编造、线索晋升防火墙。每个借鉴的"借了什么、学到什么程度、落在哪个文件、合规边界在哪"全部可追溯——完整图谱见 [docs/REFERENCES.md](docs/REFERENCES.md)。

## Adapters

| Adapter | 状态 | 说明 |
|---|---|---|
| `demo` | ✅ | 内置模拟数据（含投毒样本），clone 即跑 |
| `vacuum_b2b_sample` | ✅ | 真空工业 B2B 平台适配示例（脱敏），站点侧私有集成已落地 |

## License

MIT
