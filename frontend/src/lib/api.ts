/** API + SSE consumption (authority: docs/specs/03-api-spec.md). */

import { fetchEventSource } from "@microsoft/fetch-event-source";
import type { ChatEventData, ChatEventName, UiConfig } from "./types";

const ENDPOINT = (window as unknown as { RFQ_ENDPOINT?: string }).RFQ_ENDPOINT ?? "";

export async function fetchUiConfig(): Promise<UiConfig> {
  const res = await fetch(`${ENDPOINT}/api/v1/ui-config`);
  if (!res.ok) throw new Error(`ui-config ${res.status}`);
  return (await res.json()) as UiConfig;
}

export async function createSession(userRef: string | null = null): Promise<string> {
  const res = await fetch(`${ENDPOINT}/api/v1/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_ref: userRef }),
  });
  if (!res.ok) throw new Error(`sessions ${res.status}`);
  const data = (await res.json()) as { session_id: string };
  return data.session_id;
}

interface StreamOptions {
  sessionId: string;
  message: string;
  action?: "confirm_inquiry" | "cancel_inquiry";
  contact?: { name?: string; phone?: string } | null;
  quantity?: number | null;
  productId?: string | null;
  signal?: AbortSignal;
  onEvent: (event: ChatEventName, data: ChatEventData) => void;
}

export async function streamChat(options: StreamOptions): Promise<void> {
  const { onEvent, signal, ...body } = options;
  await fetchEventSource(`${ENDPOINT}/api/v1/chat/stream`, {
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
  await fetch(`${ENDPOINT}/api/v1/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, message_id: messageId, feedback }),
  });
}
