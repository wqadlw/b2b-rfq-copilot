/** MessageBubble — 形态参考 vercel/ai-chatbot ai-elements/Message：
 *  role 决定布局方向与容器；AI 侧带头像点与状态行；用户侧主色气泡。 */

import type { ReactElement } from "react";
import { Bot } from "lucide-react";
import { Streamdown } from "streamdown";
import { cn } from "../../lib/utils";
import type { ChatMessage } from "../../lib/types";

export function MessageBubble({
  message,
  streaming,
}: {
  message: ChatMessage;
  streaming?: boolean;
}): ReactElement {
  const isUser = message.role === "user";
  return (
    <div className={cn("flex w-full flex-col gap-1", isUser ? "items-end" : "items-start")}>
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
            <Bot className="h-3.5 w-3.5 text-primary" />
          </span>
        )}
        <div
          className={cn(
            "rounded-xl px-3 py-2 text-sm leading-relaxed whitespace-pre-wrap break-words",
            isUser ? "bg-primary text-white" : "border border-line bg-surface",
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
    </div>
  );
}

function Caret(): ReactElement {
  return (
    <span className="inline-block h-4 w-0.5 animate-pulse bg-primary align-middle" aria-hidden />
  );
}
