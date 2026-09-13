/** CitationCard — 引用来源 chip（trust 决定色彩，形态参考 FRONTEND_STYLE_GUIDE §7）。 */

import type { ReactElement } from "react";
import { BookOpen } from "lucide-react";
import { cn } from "../../lib/utils";

export interface Citation {
  index: number;
  title: string;
  trust: string;
}

const TRUST_STYLE: Record<string, string> = {
  platform: "text-success border-success/40",
  merchant: "text-warning border-warning/40",
  ugc: "text-ink-muted border-line",
};

export function CitationCard({ citation }: { citation: Citation }): ReactElement {
  return (
    <span
      className={cn(
        "inline-flex max-w-full items-center gap-1 rounded-md border bg-surface px-1.5 py-0.5 text-[11px]",
        TRUST_STYLE[citation.trust] ?? "border-line text-ink-muted",
      )}
    >
      <BookOpen className="h-3 w-3 shrink-0" />
      <span className="mono shrink-0">[{citation.index}]</span>
      <span className="truncate">{citation.title}</span>
    </span>
  );
}
