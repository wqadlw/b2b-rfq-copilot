/** API + SSE consumption (authority: docs/specs/03-api-spec.md). */

import { fetchEventSource } from "@microsoft/fetch-event-source";
import type { ChatEventData, ChatEventName, UiConfig } from "./types";

export async function fetchUiConfig(): Promise<UiConfig> {
  const res = await fetch("/api/v1/ui-config");
  if (!res.ok) throw new Error(`ui-config ${res.status}`);
  return (await res.json()) as UiConfig;
}

export async function createSession(userRef: string | null = null): Promise<string> {
  const res = await fetch("/api/v1/sessions", {
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
  onEvent: (event: ChatEventName, data: ChatEventData) => void;
}

export async function streamChat(options: StreamOptions): Promise<void> {
  const { onEvent, ...body } = options;
  await fetchEventSource("/api/v1/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    openWhenHidden: true,
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
