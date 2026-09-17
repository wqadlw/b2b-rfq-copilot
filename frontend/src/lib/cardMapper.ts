import type { ChatEventData, EntityCardData } from "./types";

/**
 * SSE `card` 事件 → 卡片数据（审查 R1 修复的单一事实源）。
 *
 * 背景：此前该映射内联在 ChatWidget 的 SSE 处理器里，新增 solution/case/
 * inquiry_status 三种卡片时字段未同步，导致三卡在浏览器渲染为空壳（title/
 * pain_points/metrics/status_text 全部丢失，且 solution 卡 name 取空）。
 * 抽为纯函数后可被单测锁定：任何新卡 kind 忘映射字段都会在 CI 失败。
 */
export function toEntityCard(data: ChatEventData): EntityCardData {
  const asString = (v: unknown): string | undefined =>
    v === undefined || v === null ? undefined : String(v);
  return {
    kind: data.kind as EntityCardData["kind"],
    // 产品/供应商卡用 name，方案/案例卡用 title —— 两者兼容
    name: String(data.name ?? data.title ?? ""),
    supplier: asString(data.supplier),
    price: asString(data.price),
    url: asString(data.url),
    specs: (data.specs as Record<string, string>) ?? undefined,
    region: data.region === undefined ? undefined : (data.region as string | null),
    certs: (data.certs as string[]) ?? undefined,
    main_products: (data.main_products as string[]) ?? undefined,
    description: asString(data.description),
    // solution
    title: asString(data.title),
    industry: asString(data.industry),
    subtitle: asString(data.subtitle),
    pain_points: (data.pain_points as EntityCardData["pain_points"]) ?? undefined,
    topology: asString(data.topology),
    budget: asString(data.budget),
    suppliers: (data.suppliers as EntityCardData["suppliers"]) ?? undefined,
    // case
    customer: asString(data.customer),
    metrics: (data.metrics as EntityCardData["metrics"]) ?? undefined,
    has_whitepaper: data.has_whitepaper === undefined ? undefined : Boolean(data.has_whitepaper),
    // inquiry_status
    inquiry_id: asString(data.inquiry_id),
    status_text: asString(data.status_text),
    quote_count: data.quote_count === undefined ? undefined : Number(data.quote_count),
  };
}
