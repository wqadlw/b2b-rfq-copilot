# b2b-rfq-copilot

> **通用垂直行业 B2B 智能询盘引擎（RFQ Copilot）** — 一个可接入不同垂直行业 B2B 平台的 AI 询盘 Agent 引擎，通过端口/适配器与能力清单机制对接站点的产品、供应商、知识库、询盘与线索分发系统。真空行业 B2B 平台是第一个落地实例。

**状态**：🚧 活跃开发中（M0 骨架阶段）· 文档先行，代码随后

## 它解决什么

B2B 平台的访客咨询散落在浏览行为里，转化依赖人工客服。本引擎把咨询变成**结构化询盘**：AI 接待 → 理解需求 → 检索产品与知识 → 澄清缺失字段 → 用户确认 → 询盘落库 → 高价值线索分发。

## 核心特性

- **端口/适配器架构**：5 个端口（产品/供应商/知识/询盘/线索）抽象 Core 与站点；新行业只需实现一个 adapter 包
- **Capability Manifest**：站点声明自己有什么能力（YAML）；没有的能力（如公开价格）→ 工具物理不注册 + 拒绝话术自动注入 + **负向评测用例自动生成**
- **拒绝编造**：AI 永不编造价格区间、货期、库存——无数据源一律确定性话术
- **检索投毒防御**：商户提交内容按不可信处理（信任三级 + 指令隔离 + 写操作用户确认门 + 输出过滤）
- **生产工程**：SSE 流式 · LangGraph 检查点 · 分层模型成本控制 · Langfuse 追踪 · 程序化断言评测（B/C/D 族不用 LLM 打分）

## 架构一瞥

```text
Core（通用引擎）──依赖──▶ 5 Ports + Manifest
   ▲
Adapters（demo 内置模拟数据 · vacuum_b2b 真实行业示例）
   ▲
Your Site（/internal-api/* · 询盘落库 · 线索分发）
```

详见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## Quickstart（M0 后可用）

```bash
git clone https://github.com/<you>/b2b-rfq-copilot.git
cd b2b-rfq-copilot
cp .env.example .env         # 填 1 个 LLM API Key
docker compose up            # 打开 http://localhost:8000 即可对话
```

> 目标验收线：clone → 1 个 Key → 10 分钟内可聊天/搜产品/创建模拟询盘/看到引用来源。

## 文档

| 文档 | 内容 |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 架构总览 |
| [docs/specs/01-port-spec.md](docs/specs/01-port-spec.md) | 端口/manifest/装配/评测派生（唯一权威） |
| [docs/FRONTEND_STYLE_GUIDE.md](docs/FRONTEND_STYLE_GUIDE.md) | 视觉规范与组件库 |
| [docs/specs/06-eval-spec.md](docs/specs/06-eval-spec.md) | 评测体系（含自动派生红队用例） |
| [docs/policies/repo-policy.md](docs/policies/repo-policy.md) | 仓库政策 |

## Adapters

| Adapter | 状态 | 说明 |
|---|---|---|
| `demo` | 🚧 M0 | 内置模拟数据，clone 即跑 |
| `vacuum_b2b` | 📋 已出规格 | 真空工业 B2B 平台（首个真实落地实例，站点侧私有集成） |

## License

MIT
