# ADR-0001 · 技术栈冻结清单（Tech Stack Freeze）

> 公开 ADR · 对应内部决策 ADR-006/008/009 · 日期：2026-09-12 · 状态：已冻结
> 规则：本清单所列选型在 M5 前不得更换；确需变更 = 新 ADR + 人类批准 + 评测全量回归。

## 冻结决策

| 维度 | 冻结值 | 落点 |
|---|---|---|
| Python | **3.12**（不取 3.11） | pyproject `requires-python = ">=3.12"` |
| Python 包管理 | **uv**（lockfile 提交） | uv.lock |
| Lint / Format | **Ruff**（单工具双职责） | pyproject |
| 类型检查 | **mypy strict** | pyproject |
| 后端框架 | **FastAPI** | app/ |
| Schema | **Pydantic v2**（边界数据唯一方式） | ports/ + schemas/ |
| 配置加载 | **pydantic-settings** | config/ |
| 测试 | **pytest + pytest-asyncio**（coverage ≥ core/policies 90%） | backend/tests/ |
| Agent 编排 | **LangGraph**（PostgresSaver；demo 用 MemorySaver） | core/agent |
| 数据库/向量 | **PostgreSQL 16 + pgvector**（HNSW）；demo 形态 SQLite+BM25 | docker-compose |
| Embedding | **BAAI/bge-m3** | core/rag |
| Rerank | **BAAI/bge-reranker-v2-m3**（可走 SiliconFlow 类 API；demo 关闭） | core/rag |
| LLM 接口 | **OpenAI 兼容端点**（DeepSeek / Qwen / GLM 系），分层模型：轻量理解 + 强模型回答 | config |
| 可观测 | **Langfuse**（云免费档或自托管）+ structlog JSON | observability/ |
| 依赖契约 | **import-linter**（CI 强制） | pyproject |
| Node | **20 LTS** | frontend |
| 前端包管理 | **pnpm**（lockfile 提交） | pnpm-lock.yaml |
| 前端框架 | **Vite + React 19 + TypeScript strict** | frontend |
| 样式/组件 | **Tailwind CSS v4（CSS-first）+ shadcn/ui（Radix）** | frontend |
| 图标 | **Lucide**（唯一主库） | frontend |
| 前端请求/状态 | **TanStack Query + Zustand + RHF + Zod + @microsoft/fetch-event-source** | frontend |
| 前端测试 | **Vitest + Testing Library**；Lint **ESLint（flat config）** | frontend |
| CI | **GitHub Actions**（七门：ruff/mypy/pytest/import-linter/前端 build+lint/repo-policy/docker build） | .github/workflows |
| 部署 | **Docker Compose**（默认 demo 单容器；`--profile prod` 全件） | docker-compose |

## 被否决的备选（防反复摇摆）

| 备选 | 否决理由 |
|---|---|
| Python 3.11 | 3.12 已成熟，项目绿field无兼容包袱（ADR-009） |
| poetry / pip-tools | uv 快、锁文件质量高、2026 事实标准 |
| Qdrant | 独立组件运维成本 > 收益，数据量级不需要（ADR-006） |
| Next.js | Demo 前台无 SSR/SEO 诉求，Vite 更轻（ADR-008） |
| Ant Design / MUI | 风格偏传统后台，不符合 Industrial AI Clean（ADR-008） |
| 原生 EventSource | 仅支持 GET，聊天需 POST+body |
| Dify 平台化搭建 | 配置不构成引擎工程能力，宪法 §0 需求一否决 |

## 版本微调政策

lockfile 内 minor/patch 升级随依赖 renovate/dependabot 常规进行；**跨大版本或换供应商** = 新 ADR + 全量评测回归（B/C/D 100%）+ 人类批准。

**Python 3.12 兼容性条款（2026-09-12 评审补充）**：Python 3.12 为冻结版本；LangGraph/FastAPI/Pydantic v2/pgvector 驱动/Langfuse SDK/测试工具链须在 3.12 下验证兼容（uv 管理解释器，CI 矩阵锁定 3.12）；如关键依赖不兼容，须通过新 ADR 变更，不得静默降级 3.11。

---
*维护者：工程组 · 冻结于 2026-09-12，M5 前生效*
