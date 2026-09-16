/** Types aligned with backend Pydantic schemas (schemas/chat.py, schemas/events.py). */

export interface UiConfig {
  adapter: string;
  display_name: string;
  chat: {
    welcome_message: string | null;
    suggested_questions: string[];
    wechat?: {
      qrcode_url: string | null;
      contact_name: string | null;
      guidance_text: string | null;
    };
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
  | "card"
  | "inquiry_confirm"
  | "inquiry_created"
  | "handoff"
  | "error"
  | "wechat_guidance"
  | "login_required"
  | "token_budget_exceeded"
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
  qrcode_url?: string;
  guidance?: string;
  contact_name?: string;
  kind?: string;
  name?: string;
  supplier?: string;
  price?: string;
  url?: string;
  specs?: Record<string, string>;
  region?: string | null;
  certs?: string[];
  main_products?: string[];
  description?: string;
}

export interface EntityCardData {
  kind: "product" | "supplier" | "solution" | "case" | "inquiry_status";
  name: string;
  supplier?: string;
  price?: string;
  url?: string;
  specs?: Record<string, string>;
  region?: string | null;
  certs?: string[];
  main_products?: string[];
  description?: string;
}

export interface Citation {
  index: number;
  title: string;
  trust: string;
}

export interface WechatQr {
  url: string;
  contact: string;
  guidance?: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  statusLine?: string;
  inquiryCreated?: boolean;
  citations?: Citation[];
  cards?: EntityCardData[];
  error?: boolean;
  wechatGuidance?: string;
  wechatQr?: WechatQr;
  loginRequired?: boolean;
  feedback?: "helpful" | "not_helpful" | null;
}
