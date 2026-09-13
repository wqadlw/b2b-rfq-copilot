/** Types aligned with backend Pydantic schemas (schemas/chat.py, schemas/events.py). */

export interface UiConfig {
  adapter: string;
  display_name: string;
  chat: {
    welcome_message: string | null;
    suggested_questions: string[];
  };
  theme: { primary: string | null };
  capabilities: Record<string, boolean>;
  inquiry: {
    guest_allowed: boolean;
    required_fields: string[];
  };
  i18n: string;
}

export type ChatEventName =
  | "status"
  | "tool_call"
  | "retrieval"
  | "answer_delta"
  | "citation"
  | "inquiry_confirm"
  | "inquiry_created"
  | "handoff"
  | "error"
  | "done";

export interface ChatEventData {
  delta?: string;
  message?: string;
  tool?: string;
  confirm_id?: string;
  draft_json?: string;
  draft?: Record<string, unknown>;
  index?: number;
  title?: string;
  trust?: string;
  inquiry_id?: string | number;
  code?: string;
  reason?: string;
}

export interface Citation {
  index: number;
  title: string;
  trust: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  statusLine?: string;
  inquiryCreated?: boolean;
  citations?: Citation[];
  error?: boolean;
  feedback?: "helpful" | "not_helpful" | null;
}
