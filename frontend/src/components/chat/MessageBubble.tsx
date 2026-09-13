/** MessageBubble — 形态参考 vercel/ai-chatbot ai-elements/Message：
 *  role 决定布局方向与容器；AI 侧带头像点与状态行；用户侧主色气泡。
 *  助手消息完成后带操作行（复制/👍/👎，P0 打磨）。 */

import { useState, type ReactElement } from "react";
import { Check, Copy, Sparkles, ThumbsDown, ThumbsUp } from "lucide-react";
import { Streamdown } from "streamdown";
import { cn } from "../../lib/utils";
import type { ChatMessage } from "../../lib/types";

export function MessageBubble({
  message,
  streaming,
  onCopy,
  onFeedback,
}: {
  message: ChatMessage;
  streaming?: boolean;
  onCopy?: (text: string) => void;
  onFeedback?: (kind: "helpful" | "not_helpful") => void;
}): ReactElement {
  const isUser = message.role === "user";
  const [copied, setCopied] = useState(false);
  const showActions = !isUser && !streaming && message.content.length > 0 && !message.error;

  const handleCopy = (): void => {
    onCopy?.(message.content);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className={cn("rfq-fade-in flex w-full flex-col gap-1", isUser ? "items-end" : "items-start")}>
      {message.statusLine && (
        <div className="flex items-center gap-1.5 text-xs text-ink-muted">
          <span className="inline-flex gap-0.5">
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                className="h-1 w-1 animate-bounce rounded-full bg-ink-muted"
                style={{ animationDelay: `${i * 150}ms` }}
              />
            ))}
          </span>
          {message.statusLine}
        </div>
      )}
      <div className={cn("flex max-w-[88%] items-end gap-2", isUser && "flex-row-reverse")}>
        {!isUser && (
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-primary-light">
            <Sparkles className="h-3.5 w-3.5 text-primary" />
          </span>
        )}
        <div
          className={cn(
            "rounded-xl px-3 py-2 text-sm leading-relaxed whitespace-pre-wrap break-words",
            isUser ? "bg-primary text-white" : "border border-line bg-surface",
            message.error && "border-danger/60 bg-danger/5",
            message.inquiryCreated && "border-success/50",
          )}
        >
          {isUser
            ? message.content
            : message.content
              ? <Streamdown>{message.content}</Streamdown>
              : streaming
                ? <Caret />
                : ""}
          {message.inquiryCreated && <p className="mt-1 text-xs text-success">询盘已创建 ✓ 后台可查</p>}
        </div>
      </div>
      {showActions && (
        <div className="ml-8 flex items-center gap-2 text-ink-muted">
          <button
            type="button"
            onClick={handleCopy}
            aria-label="复制回答"
            className="inline-flex items-center gap-0.5 text-[11px] transition-colors hover:text-primary"
          >
            {copied ? <Check className="h-3 w-3 text-success" /> : <Copy className="h-3 w-3" />}
            {copied ? "已复制" : "复制"}
          </button>
          {onFeedback && (
            <>
              <button
                type="button"
                aria-label="有帮助"
                disabled={message.feedback !== null && message.feedback !== undefined}
                onClick={() => onFeedback("helpful")}
                className={cn(
                  "transition-colors hover:text-success disabled:opacity-40",
                  message.feedback === "helpful" && "text-success",
                )}
              >
                <ThumbsUp className="h-3 w-3" />
              </button>
              <button
                type="button"
                aria-label="没帮助"
                disabled={message.feedback !== null && message.feedback !== undefined}
                onClick={() => onFeedback("not_helpful")}
                className={cn(
                  "transition-colors hover:text-danger disabled:opacity-40",
                  message.feedback === "not_helpful" && "text-danger",
                )}
              >
                <ThumbsDown className="h-3 w-3" />
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function Caret(): ReactElement {
  return (
    <span className="inline-block h-4 w-0.5 animate-pulse bg-primary align-middle" aria-hidden />
  );
}
