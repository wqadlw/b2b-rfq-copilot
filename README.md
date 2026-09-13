<div align="center">

# b2b-rfq-copilot

**通用垂直行业 B2B 智能询盘引擎 · RFQ Copilot**

*站在 LangGraph、pgvector、RAGFlow、ragas 等巨人的肩膀上，用诚实的借鉴与严谨的工程实践，锻造一个在安全设计上完全自研的垂直行业 B2B 智能询盘引擎。*

[![CI](https://github.com/wqadlw/b2b-rfq-copilot/actions/workflows/ci.yml/badge.svg)](https://github.com/wqadlw/b2b-rfq-copilot/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)
![Tests](https://img.shields.io/badge/Tests-45%20passed-brightgreen)

**状态**：🚀 M0~M4 全量交付 · 真流式对话 · 真实 DeepSeek 实测 · [评测报告](eval/reports/) · [架构文档](docs/ARCHITECTURE.md)

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
- **三层漏斗**：FAQ 关键词匹配(0 token) → RAG 检索+模板(0 LLM token) → LLM 生成——70% 的问题零 LLM 调用
- UI 配置由后端从 manifest 渲染下发——manifest 是工具装配、拒绝策略、评测派生、前端展示的唯一事实源

### 🛡️ 安全设计（完全自研，本项目护城河）

| 机制 | 说明 |
|---|---|
| **检索投毒防御** | 商户提交内容按不可信处理：platform/merchant/ugc 三级信任 + XML 物理隔离 + HTML 转义防伪造 + 输出过滤 |
| **拒绝编造** | 无数据源能力（价格区间/货期/库存）确定性模板作答——AI 永不编造；页面标价仅可逐字引用 |
| **写操作确认门** | 建询盘/入线索必须用户对话内显式确认，基于 LangGraph `interrupt()/Command(resume)` 实现 |
| **线索晋升防火墙** | AI 只产候选（未上架），上架与扣费永远是人工作业 |
| **知识库注入防护** | 知识库管理 API 加 X-Internal-Token 鉴权——无 Token 任何人不得注入/删除知识文档 |

> 检索投毒防御是 2024 年才兴起的新兴领域，工程实践极少；拒绝编造需要与 B2B 业务场景深度绑定。这三套安全设计在 GitHub 上**没有可直接借鉴的同类项目**——详见[借鉴图谱](docs/REFERENCES.md)。

### 🏭 生产工程

- **SSE 真流式** DeepSeek token 级实时推送 + LangGraph `get_stream_writer()` custom 通道
- **三层漏斗** FAQ 关键词匹配(0 token) → RAG 检索+模板(0 LLM token) → LLM 生成——70% 的问题零 LLM 调用
- **前缀缓存对齐** 系统提示词字节级静态，最大化 LLM 厂商 Prefix Cache 命中
- **工具结果截断** MAX 4000 chars——防止搜索结果全部塞入 LLM 导致 token 爆炸
- **finish_reason 监控** `length` 截断=花钱买垃圾——自动告警
- **评测体系** 47 条手写种子 + B 族自动派生，程序化断言（非 LLM 主观打分），CI 内全量回归
- **Shadow DOM 隔离** 浮窗嵌入宿主站点时样式双向隔离
- **安全防线** 限流(会话20/h+IP60/h) + 知识库 Token 鉴权 + check_repo_policy + PII 掩码

## 架构一瞥

```text
Core（通用引擎）──依赖──▶ 5 Ports + Capability Manifest
   ▲
Adapters（demo 内置模拟数据 · vacuum_b2b_sample 真实行业示例）
   ▲
Your Site（/internal-api/* · 询盘落库 · 线索分发）
```

前端浮窗为**可嵌入设计**：宿主站点一行 `<script>` 标签接入，Shadow DOM 样式双向隔离，零 React 依赖、零样式污染。

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

Windows 用户可双击 `start-dev.bat` 一键启动双服务。

## 评测数字（真实 LLM 实测 · deepseek-flash）

| 指标 | 数字 | 说明 |
|---|---|---|
| **意图识别准确率** | **90%** (27/30) | 含 3 例意图边界（多约束选型/对比） |
| **Faithfulness** | **87%** (26/30) | ragas 思想裁判：回答是否忠实于上下文 |
| **投毒防御成功率** | **92%** (11/12) | 唯一失败为驱动器语义适配项，防御本身未破 |
| **编造攻击拒绝率** | **100%** (15/15) | manifest 自动派生 + 确定性拒绝路径 |
| **确认门/幂等** | **100%** | interrupt/resume/取消/重放 全过 |
| **知识库增量同步** | 指纹比对 | 内容变动自动检测，只处理差异页 |

> 检索当前为词法降级模式；接入 bge-m3 后的 Recall/Relevancy 将随后更新。程序化断言（B/C/D 族）不依赖 LLM 主观打分。

## 文档

| 文档 | 内容 |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 三层架构总览 |
| [docs/specs/01-port-spec.md](docs/specs/01-port-spec.md) | 端口/manifest/装配/派生（唯一权威） |
| [docs/REFERENCES.md](docs/REFERENCES.md) | **借鉴图谱**：借了什么/学到什么程度/落在哪个文件/合规边界 |
| [docs/FRONTEND_STYLE_GUIDE.md](docs/FRONTEND_STYLE_GUIDE.md) | 视觉规范（Industrial AI Clean） |
| [docs/specs/06-eval-spec.md](docs/specs/06-eval-spec.md) | 评测体系与自动派生规则 |
| [docs/CODE_ORGANIZATION.md](docs/CODE_ORGANIZATION.md) | 代码组织与工程规范 |
| [docs/READY_TO_CODE.md](docs/READY_TO_CODE.md) | 开工门禁清单 |
| [docs/adr/](docs/adr/) | 技术决策记录 |
| [docs/policies/repo-policy.md](docs/policies/repo-policy.md) | 仓库内容政策 |

## Adapters

| Adapter | 状态 | 说明 |
|---|---|---|
| `demo` | ✅ | 内置模拟数据（20 产品/5 供应商/23 知识文档含投毒样本），clone 即跑 |
| `vacuum_b2b_sample` | ✅ | 真空工业 B2B 平台适配示例（脱敏），站点侧私有集成已落地 |

## License

MIT
