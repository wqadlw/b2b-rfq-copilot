/** Capability badges rendered from ui-config (manifest is the single source of truth). */

import type { ReactElement } from "react";
import { cn } from "../../lib/utils";

export function CapabilityBadge({ label, enabled }: { label: string; enabled: boolean }): ReactElement {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md px-1.5 py-0.5 text-xs",
        enabled ? "bg-primary-light text-primary" : "bg-line/60 text-ink-muted line-through",
      )}
    >
      {label}
      {!enabled && <span className="ml-1 no-underline">未启用</span>}
    </span>
  );
}
