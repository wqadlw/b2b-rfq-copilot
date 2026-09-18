/** ChatWidget — 大厂级重写：真实形态参考 vercel/ai-chatbot ai-elements 族。
 *  头部状态点 + 能力徽章；空态欢迎+引导 chips；消息气泡族；确认卡字段表；确认卡；自适应输入区。
 *  P0：停止生成(AbortController) / 一键复制 / feedback 接线 / 错误重试 / 确认卡字段表。 */

import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type ReactElement,
} from "react";
import { AlertCircle, ArrowUp, CheckCircle2, Loader2, Pencil, Sparkles, Square, X } from "lucide-react";
import { Button } from "../ui/button";
import { CitationCard } from "./CitationCard";
import {
  CaseCard,
  InquiryStatusCard,
  ProductCard,
  SolutionCard,
  SupplierCard,
} from "./EntityCard";
import type { EntityCardData } from "../../lib/types";
import { MessageBubble } from "./MessageBubble";
import { SuggestionChips } from "./SuggestionChips";
import { toEntityCard } from "../../lib/cardMapper";
import { createSession, fetchUiConfig, sendFeedback, streamChat } from "../../lib/api";
import { cn } from "../../lib/utils";
import { createInquiryCardState, inquiryReducer } from "../../lib/inquiryReducer";
import type { ChatMessage, UiConfig } from "../../lib/types";

const NEAR_BOTTOM_PX = 80;

// 输入框轮播占位语：采购高频问法轮播展示（每 4s 切换，busy 时固定"正在生成…"）
const PLACEHOLDER_ROTATIONS: string[] = [
  "找一台无油真空泵…",
  "旋片泵和干式螺杆泵怎么选…",
  "想要一套高真空机组方案…",
  "分子泵维修保养找谁…",
  "采购真空阀门，帮忙询价…",
];

function productName(productId: string | number): string {
  return DEMO_PRODUCT_NAMES[String(productId)] ?? `产品 ${productId}`;
}

const DEMO_PRODUCT_NAMES: Record<string, string> = {
  "demo-p-001": "demo 设备 真空泵 001 型",
  "demo-p-002": "demo 设备 真空泵 002 型",
  "demo-p-003": "demo 设备 真空泵 003 型",
  "demo-p-004": "demo 设备 真空泵 004 型",
  "demo-p-005": "demo 设备 真空泵 005 型",
};

interface PendingConfirm {
  card: import("../../lib/inquiryReducer").InquiryCardState;
  override?: { quantity?: number | null; contact_name?: string; contact_phone?: string };
  draft: {
    product_id?: string | number | null;
    quantity?: number | null;
    contact_name?: string;
    contact_phone_masked?: string;
    missing_fields?: string[];
  };
}

export function ChatWidget({
  initialUserRef,
  aiTicket,
  widgetMode = "production",
  loginUrl = "",
}: {
  /** 宿主站点注入的初始身份（嵌入模式由 blade 按 auth 状态传入） */
  initialUserRef?: string;
  /** E1 鉴权桥：宿主签发的 HMAC 短时票据，创建会话时透传验签 */
  aiTicket?: string;
  /** demo：显示分级访问演示条（假登录切换）；production：游客态显示可关闭的登录引导 */
  widgetMode?: "demo" | "production";
  /** 宿主登录页 URL（data-login-url 注入）；为空则不渲染登录引导链接 */
  loginUrl?: string;
} = {}): ReactElement {
  const [config, setConfig] = useState<UiConfig | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  // 分级访问演示：真实站点由宿主签发 user_ref；demo 用模拟登录按钮切换游客/登录态
  const [userRef, setUserRef] = useState<string | null>(initialUserRef ?? null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [pendingConfirm, setPendingConfirm] = useState<PendingConfirm | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const stickToBottom = useRef(true);
  const abortRef = useRef<AbortController | null>(null);
  const lastUserMessage = useRef<string>("");
  const [expandedCards, setExpandedCards] = useState<Record<number, boolean>>({});
  // 生产态游客登录引导：用户可关闭（会话内不再出现）
  const [showLoginHint, setShowLoginHint] = useState(true);
  // 轮播占位语下标：4s 切换（busy 时暂停轮播，placeholder 固定"正在生成…"）
  const [phIndex, setPhIndex] = useState(0);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setPhIndex((i) => (i + 1) % PLACEHOLDER_ROTATIONS.length);
    }, 4000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    void (async () => {
      // 审查修复：ui-config 拉取失败（宿主未配 endpoint/后端抖动）时用内置兜底，
      // 保证聊天面板（含输入框）永不空白——这是嵌入态的容错底线。
      let cfg: UiConfig;
      try {
        cfg = await fetchUiConfig();
      } catch {
        cfg = {
          adapter: "fallback",
          display_name: "AI 采购助手",
          chat: {
            welcome_message: "您好，我是找真空 AI 采购助手。可以帮您找产品、查方案、发起询盘。",
            suggested_questions: ["真空泵有哪些？", "食品加工有什么解决方案", "半导体行业有没有案例"],
          },
          theme: { primary: null },
          capabilities: {},
          inquiry: { guest_allowed: true },
        } as unknown as UiConfig;
      }
      setConfig(cfg);
      // localStorage 恢复（刷新不丢消息）
      const saved = localStorage.getItem("rfq-messages");
      const savedSid = localStorage.getItem("rfq-session-id");
      if (saved && savedSid) {
        try {
          const parsed = JSON.parse(saved) as ChatMessage[];
          if (parsed.length > 0) {
            setMessages(parsed);
            setSessionId(savedSid);
            return;
          }
        } catch { /* 解析失败走新建 */ }
      }
      const session = await createSession(userRef, aiTicket);
      setSessionId(session);
      setMessages([{ role: "assistant", content: cfg.chat.welcome_message ?? "您好，我是询盘助手。" }]);
    })();
  }, []);

  // 消息变更时持久化
  useEffect(() => {
    if (messages.length > 0 && sessionId) {
      localStorage.setItem("rfq-messages", JSON.stringify(messages));
      localStorage.setItem("rfq-session-id", sessionId);
    }
  }, [messages, sessionId]);

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

  const handleCopy = (text: string): void => {
    void navigator.clipboard.writeText(text);
  };

  const handleFeedback = (messageId: string, kind: "helpful" | "not_helpful"): void => {
    if (sessionId === null) return;
    setMessages((prev) =>
      prev.map((m, i) => (i === Number(messageId) ? { ...m, feedback: kind } : m)),
    );
    void sendFeedback(sessionId, messageId, kind);
  };

  const stop = (): void => {
    abortRef.current?.abort();
  };

  const send = async (
    message: string,
    action?: "confirm_inquiry" | "cancel_inquiry",
    draftOverride?: { quantity?: number | null; contact_name?: string; contact_phone?: string } | null,
  ): Promise<void> => {
    if (busy || (!message && !action)) return;
    setBusy(true);
    // 自愈：会话创建失败（如引擎重启期间加载的页面）时，发送前自动重建会话
    let sid = sessionId;
    if (sid === null) {
      try {
        sid = await createSession(userRef, aiTicket);
        setSessionId(sid);
      } catch {
        updateLast({ content: "无法连接引擎，请确认服务已启动后重试。", statusLine: undefined });
        setBusy(false);
        return;
      }
    }
    if (!action) {
      setPendingConfirm(null);
    }
    if (message) {
      lastUserMessage.current = message;
      setMessages((prev) => [...prev, { role: "user", content: message }]);
    }
    if (action === "confirm_inquiry") {
      setMessages((prev) => [...prev, { role: "user", content: "确认提交询盘" }]);
      setPendingConfirm((prev) => (prev ? { ...prev, card: inquiryReducer(prev.card, { type: "CONFIRM" }) } : prev));
    } else if (action === "cancel_inquiry") {
      setMessages((prev) => [...prev, { role: "user", content: "取消提交询盘" }]);
      setPendingConfirm(null);
    }
    setMessages((prev) => [...prev, { role: "assistant", content: "" }]);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await streamChat({
        sessionId: sid,
        message,
        action,
        userRef,
        signal: controller.signal,
        contact: { name: "demo 用户", phone: "13800000000" },
        quantity: 10,
        productId: null,
        draftOverride,
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
          } else if (name === "card" && data.kind) {
            setMessages((prev) => {
              const last = prev[prev.length - 1];
              if (last === undefined) return prev;
              const card: EntityCardData = toEntityCard(data);
              const list = [...(last.cards ?? []), card];
              return [...prev.slice(0, -1), { ...last, cards: list }];
            });
          } else if (name === "inquiry_confirm") {
            setPendingConfirm({ card: createInquiryCardState(data.confirm_id ?? ""), draft: data.draft ?? {} });
          } else if (name === "inquiry_created") {
            setPendingConfirm((prev) =>
              prev
                ? {
                    ...prev,
                    card: inquiryReducer(prev.card, { type: "CREATED", inquiryId: String(data.inquiry_id ?? "") }),
                  }
                : prev,
            );
            updateLast({ inquiryCreated: true });
          } else if (name === "wechat_guidance") {
            updateLast({
              wechatGuidance: data.guidance ?? undefined,
              wechatQr:
                data.qrcode_url !== undefined && data.qrcode_url !== ""
                  ? { url: data.qrcode_url, contact: data.contact_name ?? "专属工程师", guidance: data.guidance }
                  : undefined,
            });
          } else if (name === "login_required") {
            updateLast({ loginRequired: true });
          } else if (name === "token_budget_exceeded") {
            updateLast({ loginRequired: false });
          } else if (name === "error") {
            updateLast({ error: true });
            setPendingConfirm((prev) =>
              prev ? { ...prev, card: inquiryReducer(prev.card, { type: "SUBMIT_ERROR" }) } : prev,
            );
          }
        },
      });
    } catch {
      // ai-chatbot 模式：出错不清输入，用户可直接改后重试
      setInput(message || lastUserMessage.current);
      if (action === "confirm_inquiry") {
        setPendingConfirm((prev) =>
          prev ? { ...prev, card: inquiryReducer(prev.card, { type: "SUBMIT_ERROR" }) } : prev,
        );
      }
      if (controller.signal.aborted) {
        updateLast({ content: "已停止生成。", statusLine: undefined });
      } else {
        updateLast({ content: "连接中断，请重试。", statusLine: undefined, error: true });
      }
    } finally {
      abortRef.current = null;
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
    <div className="flex h-screen max-w-2xl flex-col">
      {/* Header：状态点 + 标题 + 能力徽章 */}
      <header className="flex items-center justify-between border-b border-line bg-surface px-4 py-3">
        <div className="flex items-center gap-2.5">
          <span className="relative flex h-8 w-8 items-center justify-center rounded-lg bg-primary-light">
            <Sparkles className="h-4 w-4 text-primary" />
            <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-success ring-2 ring-surface" />
          </span>
          <div>
            <h1 className="text-base font-semibold leading-tight">{config?.display_name ?? "询盘助手"}</h1>
            {/* 免责声明常驻 header 副标题：合规要求 AI 生成标识始终可见，且不占 composer 高度 */}
            <p className="text-[11px] leading-tight text-ink-muted">内容由 AI 生成 · 价格与货期以供应商确认为准</p>
          </div>
        </div>

      </header>

      {/* Messages */}
      <div
        ref={listRef}
        onScroll={onListScroll}
        aria-live="polite"
        className="min-h-0 flex-1 space-y-4 overflow-y-auto overflow-x-hidden p-4"
      >
        {empty && (
          <div className="flex flex-col items-center gap-3 pt-10 text-center">
            <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary-light">
              <Sparkles className="h-6 w-6 text-primary" />
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
            <MessageBubble
              message={message}
              streaming={busy && index === messages.length - 1}
              onCopy={handleCopy}
              onFeedback={(kind) => handleFeedback(String(index), kind)}
            />
            {/* 卡片已承载来源（名称+链接），引用 chips 仅在无卡片的消息展示（知识问答等） */}
            {message.citations && message.citations.length > 0 && !message.cards?.length && (
              <div className="ml-8 flex flex-wrap gap-1">
                {message.citations.map((c, ci) => (
                  <CitationCard key={ci} citation={c} />
                ))}
              </div>
            )}
            {message.cards && message.cards.length > 0 && (
              <CardStack
                cards={message.cards}
                expanded={!!expandedCards[index]}
                onToggle={() => setExpandedCards((prev) => ({ ...prev, [index]: !prev[index] }))}
                onInquiry={(card) => void send(`我要询盘：${card.name}`)}
              />
            )}
            {message.error && lastUserMessage.current !== "" && (
              <button
                type="button"
                onClick={() => void send(lastUserMessage.current)}
                className="ml-8 self-start rounded-lg border border-line px-2 py-1 text-xs text-ink-secondary transition-colors hover:border-primary hover:text-primary"
              >
                重试上一条请求
              </button>
            )}
          </div>
        ))}
        {pendingConfirm && (
          <div
            className={cn(
              "rfq-fade-in ml-auto w-[88%] rounded-xl border p-3 transition-colors",
              pendingConfirm.card.phase === "sent"
                ? "border-success/50 bg-success/5"
                : pendingConfirm.card.phase === "error"
                  ? "border-danger/50 bg-danger/5"
                  : "border-warning/60 bg-warning/10",
            )}
          >
            {pendingConfirm.card.phase === "sent" ? (
              <p className="flex items-center gap-1.5 text-sm font-semibold text-success">
                <CheckCircle2 className="h-4 w-4" />
                询盘已发送{pendingConfirm.card.inquiryId ? ` · 编号 ${pendingConfirm.card.inquiryId}` : ""}
              </p>
            ) : pendingConfirm.card.phase === "error" ? (
              <p className="flex items-center gap-1.5 text-sm font-semibold text-danger">
                <AlertCircle className="h-4 w-4" />
                提交失败，请重试
              </p>
            ) : (
              <p className="text-sm font-semibold text-ink">确认提交询盘</p>
            )}
            <dl className="mt-1.5 space-y-0.5 text-xs text-ink-secondary">
              {pendingConfirm.draft.product_id !== undefined && pendingConfirm.draft.product_id !== null && (
                <div>产品：{productName(pendingConfirm.draft.product_id)}</div>
              )}
              {pendingConfirm.card.phase === "editing" ? (
                <ReviewEditor
                  quantity={pendingConfirm.override?.quantity ?? (pendingConfirm.draft.quantity as number | null)}
                  contactName={pendingConfirm.override?.contact_name ?? pendingConfirm.draft.contact_name}
                  onChange={(patch) =>
                    setPendingConfirm((prev) => (prev ? { ...prev, override: { ...prev.override, ...patch } } : prev))
                  }
                  onSubmit={() =>
                    void send("", "confirm_inquiry", {
                      quantity: pendingConfirm.override?.quantity ?? null,
                      contact_name: pendingConfirm.override?.contact_name,
                      contact_phone: pendingConfirm.override?.contact_phone,
                    })
                  }
                />
              ) : (
                <>
                  {pendingConfirm.draft.quantity !== undefined && pendingConfirm.draft.quantity !== null && (
                    <div>数量：{pendingConfirm.draft.quantity}</div>
                  )}
                  {pendingConfirm.draft.contact_name !== undefined && (
                    <div>联系人：{pendingConfirm.draft.contact_name}</div>
                  )}
                  {pendingConfirm.draft.contact_phone_masked !== undefined && (
                    <div>电话：{pendingConfirm.draft.contact_phone_masked}</div>
                  )}
                </>
              )}
            </dl>
            {pendingConfirm.card.phase === "editing" && (
              <>
                <p className="mt-1.5 text-[11px] text-ink-muted">提交后将进入供应商报价流程，请核对以上信息。</p>
                <div className="mt-2.5 flex gap-2">
                  <Button size="sm" onClick={() => void send("", "confirm_inquiry", pendingConfirm.override ?? null)}>
                    确认提交
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => void send("", "cancel_inquiry")}>
                    取消
                  </Button>
                </div>
              </>
            )}
            {pendingConfirm.card.phase === "submitting" && (
              <div className="mt-2.5">
                <Button size="sm" disabled>
                  <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                  提交中…
                </Button>
              </div>
            )}
            {pendingConfirm.card.phase === "sent" && (
              <p className="mt-1.5 text-[11px] text-ink-muted">
                供应商将在 24 小时内回复；可添加微信工程师补充资料。
              </p>
            )}
            {pendingConfirm.card.phase === "error" && (
              <div className="mt-2.5">
                <Button size="sm" onClick={() => void send("", "confirm_inquiry", pendingConfirm.override ?? null)}>
                  重试发送
                </Button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* 分级访问：demo 构建显示演示条（假登录切换）；生产构建游客态显示可关闭的登录引导 */}
      {widgetMode === "demo" ? (
        <div className="flex items-center justify-between border-b border-border px-4 py-1.5 text-xs text-ink-muted">
          <span>
            {userRef
              ? "已登录：完整功能可用（每日 AI 额度内）"
              : "游客模式：常见问题免费答，深度咨询请登录"}
          </span>
          {userRef ? (
            <button type="button" className="text-primary hover:underline" onClick={() => setUserRef(null)}>
              退出登录（演示）
            </button>
          ) : (
            <button type="button" className="text-primary hover:underline" onClick={() => setUserRef("demo-user")}>
              登录 / 注册（演示）
            </button>
          )}
        </div>
      ) : (
        !userRef &&
        showLoginHint && (
          <div className="flex flex-wrap items-center justify-between gap-1 border-t border-line bg-primary-light/40 px-4 py-1.5 text-xs text-ink-secondary">
            <span>登录后可让 AI 匹配供应商并创建询盘</span>
            <span className="flex items-center gap-2">
              {loginUrl !== "" && (
                <a href={loginUrl} className="font-medium text-primary hover:underline">
                  登录 / 注册
                </a>
              )}
              <button
                type="button"
                aria-label="关闭提示"
                className="text-ink-muted transition-colors hover:text-ink"
                onClick={() => setShowLoginHint(false)}
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </span>
          </div>
        )
      )}
      {/* Input：容器式 composer（企业级契约：容器承担边框+焦点态，按钮排容器内部不压字；busy 同槽变停止钮） */}
      <form onSubmit={onSubmit} className="border-t border-line bg-surface p-3">
        <div className="flex items-end gap-1.5 rounded-xl border border-line bg-surface p-1.5 pl-2 transition-colors focus-within:border-primary focus-within:shadow-sm">
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
            placeholder={busy ? "正在生成…" : PLACEHOLDER_ROTATIONS[phIndex]}
            className="min-h-9 flex-1 resize-none bg-transparent px-1 py-1.5 text-sm leading-5 text-ink placeholder:text-ink-muted focus:outline-none"
          />
          {busy ? (
            <button
              type="button"
              onClick={stop}
              aria-label="停止生成"
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-ink text-white transition-transform active:scale-90"
            >
              <Square className="h-3.5 w-3.5" />
            </button>
          ) : (
            <button
              type="submit"
              disabled={!input.trim()}
              aria-label="发送"
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary text-white transition-all hover:bg-primary-hover active:scale-95 disabled:bg-line disabled:text-ink-muted"
            >
              <ArrowUp className="h-4 w-4" />
            </button>
          )}
        </div>
      </form>
    </div>
  );
}

/** CardStack — 卡片堆叠：折叠显示 3 张，展开后分页（每页 5 张，上一页/下一页）。 */
const CARDS_COLLAPSED = 3;
const CARDS_PER_PAGE = 5;

function CardStack({
  cards,
  expanded,
  onToggle,
  onInquiry,
}: {
  cards: EntityCardData[];
  expanded: boolean;
  onToggle: () => void;
  onInquiry: (card: EntityCardData) => void;
}): ReactElement {
  const [page, setPage] = useState(0);
  const totalPages = Math.max(1, Math.ceil(cards.length / CARDS_PER_PAGE));
  const safePage = Math.min(page, totalPages - 1);
  const visible = expanded
    ? cards.slice(safePage * CARDS_PER_PAGE, (safePage + 1) * CARDS_PER_PAGE)
    : cards.slice(0, CARDS_COLLAPSED);
  return (
    <div className="ml-8 flex flex-col gap-2">
      {visible.map((card, idx) =>
        card.kind === "product" ? (
          <ProductCard key={card.url || idx} card={card} onInquiry={onInquiry} />
        ) : card.kind === "solution" ? (
          <SolutionCard key={card.url || idx} card={card} />
        ) : card.kind === "case" ? (
          <CaseCard key={card.url || idx} card={card} />
        ) : card.kind === "inquiry_status" ? (
          <InquiryStatusCard key={idx} card={card} />
        ) : (
          <SupplierCard key={card.url || idx} card={card} />
        ),
      )}
      {expanded && totalPages > 1 ? (
        <div className="flex items-center gap-3 self-start text-xs text-muted-foreground">
          <button
            type="button"
            disabled={safePage === 0}
            onClick={() => setPage((prev) => Math.max(0, prev - 1))}
            className="rounded border border-border px-2 py-0.5 transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40"
          >
            上一页
          </button>
          <span data-testid="card-page">
            第 {safePage + 1} / {totalPages} 页 · 共 {cards.length} 个
          </span>
          <button
            type="button"
            disabled={safePage >= totalPages - 1}
            onClick={() => setPage((prev) => Math.min(totalPages - 1, prev + 1))}
            className="rounded border border-border px-2 py-0.5 transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40"
          >
            下一页
          </button>
        </div>
      ) : (
        cards.length > CARDS_COLLAPSED && (
          <button
            type="button"
            onClick={onToggle}
            className="self-start text-xs text-primary transition-colors hover:underline"
          >
            {expanded ? "收起" : `查看全部 ${cards.length} 个`}
          </button>
        )
      )}
    </div>
  );
}

/** ReviewEditor — 确认卡行内编辑（Baymard review-style：label+value+铅笔，逐字段编辑）。 */
function ReviewEditor({
  quantity,
  contactName,
  onChange,
  onSubmit,
}: {
  quantity: number | null | undefined;
  contactName: string | undefined;
  onChange: (patch: { quantity?: number; contact_name?: string }) => void;
  onSubmit: () => void;
}): ReactElement {
  const [editing, setEditing] = useState<"quantity" | "contact_name" | null>(null);
  const [draftQty, setDraftQty] = useState(String(quantity ?? ""));
  const [draftName, setDraftName] = useState(contactName ?? "");

  const commit = (): void => {
    if (editing === "quantity") {
      const n = Number.parseInt(draftQty, 10);
      if (Number.isFinite(n) && n > 0) onChange({ quantity: n });
    } else if (editing === "contact_name") {
      if (draftName.trim()) onChange({ contact_name: draftName.trim() });
    }
    setEditing(null);
  };

  return (
    <>
      {quantity !== undefined && quantity !== null && (
        <div className="flex items-center gap-1">
          {editing === "quantity" ? (
            <>
              <input
                autoFocus
                value={draftQty}
                onChange={(e) => setDraftQty(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") commit();
                  if (e.key === "Escape") setEditing(null);
                }}
                inputMode="numeric"
                className="w-16 rounded border border-primary bg-surface px-1 py-0.5 text-xs text-base sm:text-xs focus:outline-none"
              />
              <button type="button" aria-label="保存" onClick={commit} className="text-primary hover:underline">
                保存
              </button>
            </>
          ) : (
            <>
              <span>数量：{quantity}</span>
              <button
                type="button"
                aria-label="编辑数量"
                onClick={() => setEditing("quantity")}
                className="text-ink-muted hover:text-primary"
              >
                <Pencil className="h-3 w-3" />
              </button>
            </>
          )}
        </div>
      )}
      {contactName !== undefined && (
        <div className="flex items-center gap-1">
          {editing === "contact_name" ? (
            <>
              <input
                autoFocus
                value={draftName}
                onChange={(e) => setDraftName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") commit();
                  if (e.key === "Escape") setEditing(null);
                }}
                className="w-24 rounded border border-primary bg-surface px-1 py-0.5 text-xs text-base sm:text-xs focus:outline-none"
              />
              <button type="button" aria-label="保存" onClick={commit} className="text-primary hover:underline">
                保存
              </button>
            </>
          ) : (
            <>
              <span>联系人：{contactName}</span>
              <button
                type="button"
                aria-label="编辑联系人"
                onClick={() => setEditing("contact_name")}
                className="text-ink-muted hover:text-primary"
              >
                <Pencil className="h-3 w-3" />
              </button>
            </>
          )}
        </div>
      )}
      <button
        type="button"
        onClick={() => {
          commit();
          onSubmit();
        }}
        className="hidden"
        aria-hidden
      />
    </>
  );
}
