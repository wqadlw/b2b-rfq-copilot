/** ChatWidget — 大厂级重写：真实形态参考 vercel/ai-chatbot ai-elements 族。
 *  头部状态点 + 能力徽章；空态欢迎+引导 chips；消息气泡族；确认卡；自适应输入区。
 *  细节：智能滚动（用户上翻阅读时不打断）、发送后输入框高度复位、消息入场动画、aria-live。 */

import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent, type ReactElement } from "react";
import { Bot, SendHorizonal, User } from "lucide-react";
import { Button } from "../ui/button";
import { CapabilityBadge } from "./CapabilityBadge";
import { CitationCard } from "./CitationCard";
import { MessageBubble } from "./MessageBubble";
import { SuggestionChips } from "./SuggestionChips";
import { createSession, fetchUiConfig, streamChat } from "../../lib/api";
import type { ChatMessage, UiConfig } from "../../lib/types";

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

const NEAR_BOTTOM_PX = 80;

export function ChatWidget(): ReactElement {
  const [config, setConfig] = useState<UiConfig | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [pendingConfirm, setPendingConfirm] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const stickToBottom = useRef(true);

  useEffect(() => {
    void (async () => {
      const [cfg, session] = await Promise.all([fetchUiConfig(), createSession(null)]);
      setConfig(cfg);
      setSessionId(session);
      setMessages([{ role: "assistant", content: cfg.chat.welcome_message ?? "您好，我是询盘助手。" }]);
    })();
  }, []);

  // 智能滚动：仅当用户停留在底部附近时跟随；用户上翻阅读时不打断
  useEffect(() => {
    const el = listRef.current;
    if (el === null || !stickToBottom.current) return;
    el.scrollTo({ top: el.scrollHeight });
  }, [messages, pendingConfirm]);

  const onListScroll = (): void => {
    const el = listRef.current;
    if (el === null) return;
    stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM_PX;
  };

  const resetInput = (): void => {
    setInput("");
    const el = inputRef.current;
    if (el !== null) el.style.height = "auto"; // 发送后高度复位
  };

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
    setPendingConfirm(null);
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
          } else if (name === "citation" && data.title) {
            setMessages((prev) => {
              const last = prev[prev.length - 1];
              if (last === undefined) return prev;
              const list = [
                ...(last.citations ?? []),
                { index: data.index ?? 0, title: String(data.title), trust: String(data.trust ?? "merchant") },
              ];
              return [...prev.slice(0, -1), { ...last, citations: list }];
            });
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
    resetInput();
    void send(message);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>): void => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      const message = input.trim();
      resetInput();
      void send(message);
    }
  };

  const empty = messages.length <= 1 && !pendingConfirm;

  return (
    <div className="mx-auto flex h-screen max-w-2xl flex-col bg-background">
      {/* Header：状态点 + 标题 + 能力徽章 */}
      <header className="flex items-center justify-between border-b border-line bg-surface px-4 py-3">
        <div className="flex items-center gap-2.5">
          <span className="relative flex h-8 w-8 items-center justify-center rounded-lg bg-primary-light">
            <Bot className="h-4 w-4 text-primary" />
            <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-success ring-2 ring-surface" />
          </span>
          <div>
            <h1 className="text-base font-semibold leading-tight">{config?.display_name ?? "询盘助手"}</h1>
            <p className="text-xs text-ink-muted">在线 · 由 AI 询盘引擎驱动</p>
          </div>
        </div>
        <div className="flex max-w-[55%] flex-wrap justify-end gap-1">
          {config &&
            Object.entries(config.capabilities).map(([key, enabled]) => (
              <CapabilityBadge key={key} label={CAPABILITY_LABELS[key] ?? key} enabled={enabled} />
            ))}
        </div>
      </header>

      {/* Messages */}
      <div
        ref={listRef}
        onScroll={onListScroll}
        aria-live="polite"
        className="flex-1 space-y-4 overflow-y-auto p-4"
      >
        {empty && (
          <div className="flex flex-col items-center gap-3 pt-10 text-center">
            <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary-light">
              <Bot className="h-6 w-6 text-primary" />
            </span>
            <p className="text-sm font-medium">您好，我是采购助手</p>
            <p className="max-w-xs text-xs text-ink-muted">
              我可以帮您查产品、对参数、做选型；需要报价可直接为您创建询盘。
            </p>
            <SuggestionChips
              questions={config?.chat.suggested_questions ?? []}
              onPick={(q) => void send(q)}
            />
          </div>
        )}
        {messages.map((message, index) => (
          <div key={index} className="rfq-fade-in flex flex-col gap-1">
            <MessageBubble message={message} streaming={busy && index === messages.length - 1} />
            {message.citations && message.citations.length > 0 && (
              <div className="ml-8 flex flex-wrap gap-1">
                {message.citations.map((c, ci) => (
                  <CitationCard key={ci} citation={c} />
                ))}
              </div>
            )}
          </div>
        ))}
        {pendingConfirm && (
          <div className="rfq-fade-in ml-auto w-[88%] rounded-xl border border-warning/60 bg-warning/10 p-3">
            <p className="text-sm font-semibold text-ink">确认提交询盘</p>
            <p className="mt-1 text-xs text-ink-secondary">提交后将进入供应商报价流程，请核对以上信息。</p>
            <div className="mt-2.5 flex gap-2">
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

      {/* Input */}
      <form onSubmit={onSubmit} className="flex items-end gap-2 border-t border-line bg-surface p-3">
        <div className="relative flex-1">
          <textarea
            ref={inputRef}
            value={input}
            rows={1}
            onChange={(event) => {
              setInput(event.target.value);
              event.target.style.height = "auto";
              event.target.style.height = `${Math.min(event.target.scrollHeight, 120)}px`;
            }}
            onKeyDown={onKeyDown}
            placeholder={busy ? "对方正在输入…" : "描述您的采购需求，如：找一台无油真空泵…"}
            className="w-full resize-none rounded-xl border border-line bg-surface px-3 py-2 pr-10 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
          />
          <User className="pointer-events-none absolute bottom-2 right-3 h-3.5 w-3.5 text-ink-muted" />
        </div>
        <Button
          type="submit"
          disabled={busy || !input.trim()}
          aria-label="发送"
          className="h-9 w-9 !px-0 transition-transform active:scale-90"
        >
          <SendHorizonal className="h-4 w-4" />
        </Button>
      </form>
      <p className="pb-2 text-center text-[11px] text-ink-muted">
        内容由 AI 生成 · 价格与货期以供应商确认为准
      </p>
    </div>
  );
}
