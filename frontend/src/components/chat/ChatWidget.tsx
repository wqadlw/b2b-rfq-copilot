/** Minimal chat widget (M0): ui-config header + SSE consumption + confirm placeholder. */

import { useEffect, useRef, useState, type FormEvent, type ReactElement } from "react";
import { Bot, SendHorizonal } from "lucide-react";
import { Button } from "../ui/button";
import { CapabilityBadge } from "./CapabilityBadge";
import { createSession, fetchUiConfig, streamChat } from "../../lib/api";
import type { ChatMessage, UiConfig } from "../../lib/types";
import { cn } from "../../lib/utils";

const CAPABILITY_LABELS: Record<string, string> = {
  product_catalog: "产品",
  supplier_directory: "供应商",
  knowledge_source: "知识库",
  inquiry: "询盘",
  lead_distribution: "线索",
  pricing: "价格",
  lead_time: "货期",
  stock: "库存",
};

export function ChatWidget(): ReactElement {
  const [config, setConfig] = useState<UiConfig | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [pendingConfirm, setPendingConfirm] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void (async () => {
      const [cfg, session] = await Promise.all([fetchUiConfig(), createSession(null)]);
      setConfig(cfg);
      setSessionId(session);
      if (cfg.chat.welcome_message) {
        setMessages([{ role: "assistant", content: cfg.chat.welcome_message }]);
      }
    })();
  }, []);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [messages]);

  const updateLast = (patch: Partial<ChatMessage>): void => {
    setMessages((prev) => {
      const last = prev[prev.length - 1];
      if (last === undefined) return prev;
      return [...prev.slice(0, -1), { ...last, ...patch }];
    });
  };

  const appendDelta = (delta: string): void => {
    setMessages((prev) => {
      const last = prev[prev.length - 1];
      if (last === undefined) return prev;
      return [...prev.slice(0, -1), { ...last, content: last.content + delta, statusLine: undefined }];
    });
  };

  const send = async (message: string, action?: "confirm_inquiry" | "cancel_inquiry"): Promise<void> => {
    if (!sessionId || busy || (!message && !action)) return;
    setBusy(true);
    if (message) setMessages((prev) => [...prev, { role: "user", content: message }]);
    setMessages((prev) => [...prev, { role: "assistant", content: "" }]);
    try {
      await streamChat({
        sessionId,
        message,
        action,
        contact: { name: "demo 用户", phone: "13800000000" },
        quantity: 10,
        productId: null,
        onEvent: (name, data) => {
          if (name === "status" || name === "tool_call") {
            updateLast({ statusLine: data.message ?? `正在调用 ${data.tool ?? "工具"}…` });
          } else if (name === "answer_delta" && data.delta) {
            appendDelta(data.delta);
          } else if (name === "inquiry_confirm") {
            setPendingConfirm(data.confirm_id ?? null);
          } else if (name === "inquiry_created") {
            setPendingConfirm(null);
            updateLast({ inquiryCreated: true });
          }
        },
      });
    } catch {
      updateLast({ content: "连接中断，请重试。", statusLine: undefined });
    } finally {
      setBusy(false);
    }
  };

  const onSubmit = (event: FormEvent): void => {
    event.preventDefault();
    const message = input.trim();
    setInput("");
    void send(message);
  };

  return (
    <div className="mx-auto flex h-screen max-w-2xl flex-col bg-surface">
      <header className="flex items-center justify-between border-b border-line px-4 py-3">
        <div className="flex items-center gap-2">
          <Bot className="h-5 w-5 text-primary" />
          <h1 className="text-base font-semibold">{config?.display_name ?? "询盘助手"}</h1>
        </div>
        <div className="flex flex-wrap gap-1">
          {config &&
            Object.entries(config.capabilities).map(([key, enabled]) => (
              <CapabilityBadge key={key} label={CAPABILITY_LABELS[key] ?? key} enabled={enabled} />
            ))}
        </div>
      </header>

      <div ref={listRef} className="flex-1 space-y-3 overflow-y-auto p-4">
        {messages.map((message, index) => (
          <div
            key={index}
            className={cn(
              "max-w-[80%] rounded-xl border px-3 py-2 text-sm leading-relaxed",
              message.role === "user"
                ? "ml-auto border-primary bg-primary text-white"
                : "border-line bg-surface",
            )}
          >
            {message.statusLine && <p className="mb-1 text-xs text-ink-muted">{message.statusLine}</p>}
            {message.content || (message.statusLine ? "" : "…")}
            {message.inquiryCreated && (
              <p className="mt-1 text-xs text-success">询盘已创建 ✓（后台可查）</p>
            )}
          </div>
        ))}
        {pendingConfirm && (
          <div className="rounded-xl border border-warning/60 bg-warning/10 p-3 text-sm">
            <p className="font-medium">请确认以上询盘信息</p>
            <div className="mt-2 flex gap-2">
              <Button size="sm" onClick={() => void send("", "confirm_inquiry")}>
                确认提交
              </Button>
              <Button size="sm" variant="outline" onClick={() => void send("", "cancel_inquiry")}>
                取消
              </Button>
            </div>
          </div>
        )}
      </div>

      <form onSubmit={onSubmit} className="flex items-center gap-2 border-t border-line p-3">
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="输入您的采购需求…"
          className="h-9 flex-1 rounded-lg border border-line bg-surface px-3 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
        />
        <Button type="submit" disabled={busy || !input.trim()} aria-label="发送">
          <SendHorizonal className="h-4 w-4" />
        </Button>
      </form>
    </div>
  );
}
