# ADR-0004 · 前端栈与可嵌入聊天组件

> 公开 ADR（内部编号 ADR-008 精选）· 日期：2026-09-12 · 状态：已采纳

## 背景

需要 Demo 前台（展示用）与可嵌入宿主站点的聊天组件（落地用）；宿主站点可能是传统服务端渲染 + ES5 技术栈（如首个实例）。

## 决策

- 栈：**Vite + React 19 + TypeScript strict + Tailwind v4（CSS-first tokens）+ shadcn/ui + Lucide**；状态 Zustand、请求 TanStack Query、表单 RHF+Zod、SSE `@microsoft/fetch-event-source`（支持 POST）；风格 Industrial AI Clean（主色 #2563EB）。
- **可嵌入 widget = React 组件 + 纯 vanilla bootstrap（`rfq-chat.js`）**：宿主一行 script 标签接入，配置由 `GET /api/v1/ui-config` 下发，宿主零 React 依赖。
- 字体 @fontsource 自托管；Light/Dark 令牌 Day1 双套。

## 备选方案

- Next.js：无 SSR/SEO 诉求，过重。
- Ant Design / MUI：传统后台气质，不符风格定位。
- Web Component 全套实现：M0 复杂度高，React+bootstrap 已满足隔离诉求（Shadow DOM 兜底）。

## 后果

- 公开仓库展示效果与现代 AI 产品对齐。
- 传统站点（含 ES5 宪法的宿主）零改造嵌入。
- 前端类型与后端 Pydantic Schema 手动对齐（lib/types.ts），CI 以 build+tsc 兜底。
