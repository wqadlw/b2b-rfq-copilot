import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/**
 * 主动触达预填通道（站点 ai-proactive.js 点击 teaser 后派发 CustomEvent("rfq:prefill")）。
 * 从事件 detail 安全提取预填文案：非字符串 / 空串一律返回 current（不覆盖输入框），上限 200 字。
 * 纪律：预填只写入输入框、绝不自动发送——低承诺 CTA（业界一致实践，反模式见 outputs 主动触达方案）。
 */
export function prefillFromEvent(current: string, detail: unknown): string {
  if (typeof detail !== "object" || detail === null) return current;
  const msg = (detail as { message?: unknown }).message;
  if (typeof msg !== "string") return current;
  const trimmed = msg.trim().slice(0, 200);
  return trimmed ? trimmed : current;
}
