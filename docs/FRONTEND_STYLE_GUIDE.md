# FRONTEND STYLE GUIDE · 视觉规范与组件库

> 密级：公开 · 版本 v1.0 · 2026-09-12 · 风格定名：**Industrial AI Clean**（ADR-008）· 传达"能接入真实业务的工程系统"，不是 Demo 玩具。

## 1. 风格关键词

```text
专业 · 可信 · 工业 · 清晰 · 数据感 · AI 原生 · 低装饰 · 高可读
```

**禁止**：大面积霓虹渐变 / 玻璃拟态 / 赛博朋克 / 聊天机器人玩具风 / 全局大圆角 / 重投影。

## 2. 技术栈（冻结）

```text
React 19 + TypeScript + Vite
Tailwind CSS v4（CSS-first tokens，@theme 定义）
shadcn/ui（Radix UI 底座）
Lucide Icons（唯一主图标库）
TanStack Query（请求）· Zustand（轻状态）
React Hook Form + Zod（表单与校验）
@microsoft/fetch-event-source（SSE，支持 POST）
Recharts（评测看板图表）
@fontsource-variable/inter · @fontsource/noto-sans-sc（自托管，无运行时 CDN）
JetBrains Mono（@fontsource，参数/字段/Trace ID）
```

## 3. 色彩令牌（CSS variables，Light/Dark 双套 Day1 定义）

| 令牌 | Light | Dark | 用途 |
|---|---|---|---|
| `--background` | `#FAFAFA` | `#0A0A0B` | 页面底 |
| `--surface` | `#FFFFFF` | `#111113` | 卡片 |
| `--border` | `#E4E4E7` | `#26262A` | 细边框（1px 优先） |
| `--text-primary` | `#18181B` | `#F4F4F5` | — |
| `--text-secondary` | `#52525B` | `#A1A1AA` | — |
| `--text-muted` | `#A1A1AA` | `#71717A` | — |
| `--primary` | `#2563EB` | `#3B82F6` | 主色（信任/工业/技术） |
| `--primary-hover` | `#1D4ED8` | `#2563EB` | — |
| `--primary-light` | `#DBEAFE` | `#1E3A5F` | 主色浅底 |
| `--accent` | `#06B6D4` | `#22D3EE` | 点缀（AI/数据高亮） |
| `--success` | `#16A34A` | `#22C55E` | 询盘创建成功 / capability enabled |
| `--warning` | `#D97706` | `#F59E0B` | 能力禁用提示 / merchant 信任标 |
| `--danger` | `#DC2626` | `#EF4444` | 评测失败 / 危险操作 |

主色白标：adapter 可经 `ui-config.theme.primary` 覆盖（M4 实装，port-spec v1.1 候选）；前端所有组件禁止硬编码色值，一律走令牌。

## 4. 字体与字号

```css
font-family: "Inter Variable", "Noto Sans SC", system-ui, sans-serif;      /* 正文 */
font-family: "JetBrains Mono", ui-monospace, monospace;                     /* 参数/Trace ID/JSON */
```

| 层级 | 字号/行高 |
|---|---|
| 页面标题 | 20~24 / 32 |
| 卡片标题 | 16 / 24 |
| 正文 | 14 / 22 |
| 辅助文本 | 13 / 20 |
| 标签徽章 | 12 / 16（正文永不小于 13——B2B 数据密度要求） |

## 5. 形状与阴影

```text
圆角：按钮/输入框 8px · 卡片/聊天气泡 12px · 大容器 16px
边框：1px solid var(--border)（细边框优先于阴影）
阴影：0 1px 2px rgba(0,0,0,.04)（仅悬浮态加重到 0 4px 12px rgba(0,0,0,.08)）
间距：4px 网格（4/8/12/16/24/32）；页面留白 24px 起
```

## 6. 图标规范

- **唯一主库 Lucide**：线性图标、统一 24 viewBox、stroke 1.75px、`currentColor`。
- 工业品类图标不足时可补 Tabler Icons（`@tabler/icons-react`），**同一页面不混用两种图标风格**；品类图标统一尺寸 20px、圆角容器底色 `--primary-light`。
- 禁止 emoji 作功能图标。

## 7. 核心组件清单

| 组件 | 规格要点 |
|---|---|
| `ChatWidget` | 可嵌入聊天组件：React 组件 + vanilla bootstrap `rfq-chat.js`（script 标签挂载，宿主站点零 React 依赖）；Header（助手名+状态点+能力徽章）/ Messages / Input 三段 |
| `MessageBubble` | 用户：右对齐、`--primary` 底白字、radius 12；AI：左对齐、`--surface` 底+细边框、radius 12；AI 消息尾随 CitationCard 组 |
| `StreamingText` | answer_delta 增量渲染；光标闪烁；`aria-live="polite"` |
| `ToolCallStatus` | 工具调用状态条：Lucide 小图标 + 文案（"正在搜索产品…"）+ 三点脉冲动画；事件序列映射见 api-spec §2 |
| `CitationCard` | 图标+标题+章节+信任徽章，可点击；紧凑横向 chip 或纵向小卡 |
| `TrustBadge` | platform=绿 / merchant=橙 / ugc=灰；12px 徽章 |
| `CapabilityBadge` | 读 `ui-config.capabilities`：enabled=浅色实底徽章，disabled=灰底+"未启用"；这是 GitHub 展示的核心组件 |
| `ProductCard` | 名称/分类/供应商/关键参数（mono 字体）/价格展示（shown 原文或"联系供应商询价"）/详情链接 |
| `SupplierCard` | 名称/认证徽章组/主营/地区；并列展示不排序 |
| `InquiryConfirmCard` | 确认门专属：产品/数量/需求摘要/联系人/缺失字段高亮；主按钮"确认提交"+ 次按钮"取消"；结构清晰字段对齐 |
| `EvalDashboard` | 用例数/通过率/拒绝编造率/投毒防御成功率/P95/成本；Recharts 柱状+折线+表格；数字用 mono |
| `EmptyState` / `ErrorState` / `Skeleton` | 空态给引导动作（suggested_questions）；错误态给重试；加载用骨架屏不用转圈 |

## 8. 聊天窗口细节

1. **能力徽章区**在 Header：让访客与评审者一眼看到"这个 adapter 有什么能力"。
2. 工具调用期间**不空白等待**：status/tool_call 事件驱动状态条文案轮换（理解需求→搜索产品→整理询盘→生成回答）。
3. 引用来源紧贴 AI 消息底部，用户点击可跳转（有 url 时）。
4. 输入区：自适应高度 textarea（≤6 行）+ 发送按钮 + 快捷问题 chips（来自 ui-config）。
5. 确认卡片出现时，输入区禁用直至用户确认/取消——写操作只能经确认门。
6. 错误（SSE `error` 事件）：气泡内联提示 + 重试按钮；Policy 类结果（拒绝编造）是正常内容渲染，**不是**错误样式。

## 9. 可嵌入 Widget 契约

```html
<!-- 宿主站点（含传统服务端渲染/ES5 站点）嵌入方式 -->
<div id="rfq-chat"></div>
<script src="https://<部署域>/widget/rfq-chat.js" data-endpoint="https://<部署域>" defer></script>
```

- bootstrap 拉取 `GET /api/v1/ui-config` 渲染配置；挂载到 `#rfq-chat`（或浮动气泡模式）。
- 对外 postMessage 事件：`rfq:inquiry_created` / `rfq:handoff`（宿主可监听做统计）。
- 字体随宿主：widget 样式声明字体栈但**不强制注入 @fontsource**（宿主可选引入），保证嵌入站不受字体加载惩罚。
- 样式隔离：Shadow DOM 或前缀类名（`rfq-`）。

## 10. 主题模式与国际化

- Light/Dark 令牌 Day1 双套；一期交付 Light 优先，Dark 切换 M5（shadcn `dark` class）。
- 文案集中管理（`frontend/src/lib/copy.ts`），一期 zh-CN，结构预留 en；AI 话术规范见 `specs/04-prompt-spec.md` §3，前端不自行拟 AI 话术。

## 11. 无障碍与触控

- 焦点态可见（`focus-visible` 环）；触控目标 ≥44px；流式输出 `aria-live`；图表带表格替代数据。

## 12. 目录

```text
frontend/src/
├── app/            # 页面（Demo Chat / Eval Dashboard）
├── components/     # chat/ product/ supplier/ inquiry/ citation/ capability/ eval/ ui/
├── hooks/          # useChatStream / useUiConfig
├── lib/            # api.ts · sse.ts · types.ts（类型与后端 Pydantic Schema 对齐）· copy.ts
└── styles/         # globals.css · tokens.css（@theme）
```

类型同步：`lib/types.ts` 与后端 Pydantic 模型一一对应（M0 起用脚本生成或 CI 校验，防漂移）。

---
*维护者：工程组 · 视觉令牌变更须更新本文件 + tokens.css 同 commit*
