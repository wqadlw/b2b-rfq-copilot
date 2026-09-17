/** API + SSE consumption (authority: docs/specs/03-api-spec.md). */

import { fetchEventSource } from "@microsoft/fetch-event-source";
import type { ChatEventData, ChatEventName, UiConfig } from "./types";

/**
 * 嵌入态基址必须调用时惰性读取：bootstrap 挂载时才写入 window.RFQ_ENDPOINT，
 * 顶层 const 会在赋值前求值（bundle 加载顺序早于 mount()），固化成空串，
 * 导致嵌入态请求打到宿主站点源（Laravel 404）。
 */
function endpoint(): string {
  return (window as unknown as { RFQ_ENDPOINT?: string }).RFQ_ENDPOINT ?? "";
}

export async function fetchUiConfig(): Promise<UiConfig> {
  const res = await fetch(`${endpoint()}/api/v1/ui-config`);
  if (!res.ok) throw new Error(`ui-config ${res.status}`);
  return (await res.json()) as UiConfig;
}

export async function createSession(
  userRef: string | null = null,
  aiTicket: string | null = null,
): Promise<string> {
  const res = await fetch(`${endpoint()}/api/v1/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_ref: userRef, ai_ticket: aiTicket }),
  });
  if (!res.ok) throw new Error(`sessions ${res.status}`);
  const data = (await res.json()) as { session_id: string };
  return data.session_id;
}

interface StreamOptions {
  sessionId: string;
  message: string;
  pageType?: string;
  userRef?: string | null;
  action?: "confirm_inquiry" | "cancel_inquiry";
  contact?: { name?: string; phone?: string } | null;
  quantity?: number | null;
  productId?: string | null;
  draftOverride?: { quantity?: number | null; contact_name?: string; contact_phone?: string } | null;
  signal?: AbortSignal;
  onEvent: (event: ChatEventName, data: ChatEventData) => void;
}

export async function streamChat(options: StreamOptions): Promise<void> {
  const { onEvent, signal } = options;
  // 后端契约是 snake_case（ChatRequest）——禁止直接透传前端驼峰键
  const body = {
    session_id: options.sessionId,
    message: options.message,
    page_type: options.pageType,
    product_id: options.productId,
    user_ref: options.userRef,
    contact: options.contact,
    quantity: options.quantity,
    action: options.action,
    draft_override: options.draftOverride ?? undefined,
  };
  await fetchEventSource(`${endpoint()}/api/v1/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    openWhenHidden: true,
    signal,
    onmessage(msg) {
      const name = msg.event as ChatEventName;
      let data: ChatEventData = {};
      try {
        data = msg.data ? (JSON.parse(msg.data) as ChatEventData) : {};
      } catch {
        data = {};
      }
      onEvent(name, data);
    },
  });
}

export async function sendFeedback(
  sessionId: string,
  messageId: string,
  feedback: "helpful" | "not_helpful",
): Promise<void> {
  await fetch(`${endpoint()}/api/v1/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, message_id: messageId, feedback }),
  });
}
