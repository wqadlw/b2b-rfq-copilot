/** EntityCard — 结构化实体卡片族（产品/供应商）。
 *  形态参考：Perplexity 结构化答案卡 + Zowie 产品卡（图左文右 + 双 CTA）。
 *  工业风：克制圆角、灰阶分层、主色仅用于 CTA 与认证徽章。 */

import type { ReactElement } from "react";
import { ArrowUpRight, BadgeCheck, Building2, Package, MapPin } from "lucide-react";
import { cn } from "../../lib/utils";

export interface EntityCardData {
  kind: "product" | "supplier";
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

function certIcon(c: string): ReactElement {
  const lower = c.toLowerCase();
  if (lower.includes("iso")) return <BadgeCheck className="h-3 w-3 text-success shrink-0" />;
  if (lower.includes("实名")) return <BadgeCheck className="h-3 w-3 text-primary shrink-0" />;
  return <BadgeCheck className="h-3 w-3 text-warning shrink-0" />;
}

export function ProductCard({
  card,
  onInquiry,
}: {
  card: EntityCardData;
  onInquiry?: (card: EntityCardData) => void;
}): ReactElement {
  const specs = Object.entries(card.specs ?? {}).slice(0, 3);
  return (
    <div className="rfq-fade-in w-full max-w-[88%] self-start overflow-hidden rounded-xl border border-line bg-surface transition-shadow hover:shadow-md">
      <div className="flex items-start gap-3 p-3">
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-primary-light">
          <Package className="h-5 w-5 text-primary" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-ink">{card.name}</p>
          <p className="mt-0.5 flex items-center gap-1 text-xs text-ink-muted">
            <Building2 className="h-3 w-3 shrink-0" />
            <span className="truncate">{card.supplier ?? "平台供应商"}</span>
          </p>
          {specs.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1">
              {specs.map(([k, v]) => (
                <span
                  key={k}
                  className="mono rounded border border-line bg-background px-1.5 py-0.5 text-[10px] text-ink-secondary"
                >
                  {k}:{v}
                </span>
              ))}
            </div>
          )}
        </div>
        <div className="shrink-0 text-right">
          <p className="text-sm font-semibold text-primary">{card.price ?? "询价"}</p>
        </div>
      </div>
      <div className="flex items-center justify-between border-t border-line bg-background/60 px-3 py-2">
        <span className="text-[11px] text-ink-muted">参数与货期以供应商确认为准</span>
        <div className="flex items-center gap-1.5">
          {onInquiry && (
            <button
              type="button"
              onClick={() => onInquiry(card)}
              className="rounded-md bg-primary px-2.5 py-1 text-[11px] font-medium text-white transition-colors hover:bg-primary-hover active:scale-95"
            >
              发起询盘
            </button>
          )}
          {card.url && (
            <a
              href={card.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-0.5 rounded-md border border-primary/40 px-2 py-1 text-[11px] font-medium text-primary transition-colors hover:bg-primary-light"
            >
              查看详情
              <ArrowUpRight className="h-3 w-3" />
            </a>
          )}
        </div>
      </div>
    </div>
  );
}

export function SupplierCard({ card }: { card: EntityCardData }): ReactElement {
  const certs = card.certs ?? [];
  return (
    <div className="rfq-fade-in w-full max-w-[88%] self-start overflow-hidden rounded-xl border border-line bg-surface transition-shadow hover:shadow-md">
      <div className="flex items-start gap-3 p-3">
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-primary-light">
          <Building2 className="h-5 w-5 text-primary" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-ink">{card.name}</p>
          <p className="mt-0.5 flex items-center gap-1 text-xs text-ink-muted">
            <MapPin className="h-3 w-3 shrink-0" />
            {card.region || "地区未标注"}
          </p>
          {certs.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1">
              {certs.map((c) => (
                <span
                  key={c}
                  className={cn(
                    "inline-flex items-center gap-0.5 rounded-full border px-1.5 py-0.5 text-[10px] font-medium",
                    c.toLowerCase().includes("iso")
                      ? "border-success/40 text-success"
                      : "border-primary/30 text-primary",
                  )}
                >
                  {certIcon(c)}
                  {c}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
      {card.description && (
        <p className="line-clamp-2 px-3 pb-2 text-xs leading-relaxed text-ink-secondary">{card.description}</p>
      )}
      {(card.main_products?.length ?? 0) > 0 && (
        <div className="flex flex-wrap gap-1 px-3 pb-2.5">
          {card.main_products?.slice(0, 4).map((p) => (
            <span key={p} className="rounded bg-background px-1.5 py-0.5 text-[10px] text-ink-secondary">
              {p}
            </span>
          ))}
        </div>
      )}
      <div className="flex items-center justify-between border-t border-line bg-background/60 px-3 py-2">
        <span className="text-[11px] text-ink-muted">提交询盘 · 供应商主动联系</span>
        {card.url && (
          <a
            href={card.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-0.5 rounded-md border border-primary/40 px-2 py-1 text-[11px] font-medium text-primary transition-colors hover:bg-primary-light"
          >
            进入店铺
            <ArrowUpRight className="h-3 w-3" />
          </a>
        )}
      </div>
    </div>
  );
}
