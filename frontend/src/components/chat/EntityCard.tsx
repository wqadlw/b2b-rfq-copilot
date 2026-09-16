/** EntityCard — 结构化实体卡片族（产品/供应商）。
 *  形态参考：Perplexity 结构化答案卡 + Zowie 产品卡（图左文右 + 双 CTA）。
 *  工业风：克制圆角、灰阶分层、主色仅用于 CTA 与认证徽章。 */

import type { ReactElement } from "react";
import { ArrowUpRight, BadgeCheck, Building2, MapPin } from "lucide-react";
import { cn } from "../../lib/utils";

export interface EntityCardData {
  kind: "product" | "supplier";
  name: string;
  supplier?: string;
  brand?: string | null;
  category?: string | null;
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
  const isQuotable = !!card.price && !card.price.includes("联系") && !card.price.includes("询价");
  const badge = card.category?.slice(0, 1) || card.name.slice(0, 1);
  return (
    <div className="rfq-fade-in w-full max-w-[92%] self-start overflow-hidden rounded-xl border border-line bg-surface transition-all hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-md">
      <div className="flex gap-3 p-3">
        {/* 品类角标占位图（M5：站点 API 暴露产品图后替换为真实图） */}
        <span
          aria-hidden
          className="flex h-14 w-14 shrink-0 select-none items-center justify-center rounded-lg bg-gradient-to-br from-primary-light via-surface to-background text-lg font-bold text-primary/70 ring-1 ring-inset ring-primary/10"
        >
          {badge}
        </span>
        <div className="min-w-0 flex-1">
          <p className="line-clamp-2 text-sm font-semibold leading-snug text-ink">{card.name}</p>
          <div className="mt-1 flex min-w-0 items-center gap-1.5 text-[11px] text-ink-muted">
            <span className="truncate">{card.supplier ?? "平台供应商"}</span>
            {card.brand && (
              <>
                <span className="shrink-0 text-line">·</span>
                <span className="shrink-0 rounded bg-background px-1 py-px text-[10px] text-ink-secondary ring-1 ring-line">
                  {card.brand}
                </span>
              </>
            )}
          </div>
        </div>
        {/* 价格层：可报价大数字 / 询价徽章 */}
        <div className="shrink-0 self-center text-right">
          {isQuotable ? (
            <p className="text-base font-bold tabular-nums leading-5 text-primary">{card.price}</p>
          ) : (
            <span className="inline-block rounded bg-background px-1.5 py-0.5 text-[11px] font-medium text-ink-secondary ring-1 ring-line">
              可询价
            </span>
          )}
        </div>
      </div>
      {specs.length > 0 && (
        <div className="grid grid-cols-3 gap-2 px-3 pb-3">
          {specs.map(([k, v]) => (
            <div key={k} className="rounded-lg bg-background px-2 py-1.5 ring-1 ring-line/70">
              <p className="truncate text-[10px] leading-3 text-ink-muted" title={k}>
                {k}
              </p>
              <p className="mono mt-1 truncate text-[12px] font-semibold text-ink" title={v}>
                {v}
              </p>
            </div>
          ))}
        </div>
      )}
      <div className="flex items-center justify-end gap-1.5 border-t border-line bg-background/60 px-3 py-2">
        {card.url && (
          <a
            href={card.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-0.5 rounded-md px-2 py-1 text-[11px] font-medium text-ink-secondary transition-colors hover:text-primary"
          >
            查看详情
            <ArrowUpRight className="h-3 w-3" />
          </a>
        )}
        {onInquiry && (
          <button
            type="button"
            onClick={() => onInquiry(card)}
            className="rounded-md bg-primary px-2.5 py-1 text-[11px] font-medium text-white shadow-sm transition-all hover:bg-primary-hover active:scale-95"
          >
            发起询盘
          </button>
        )}
      </div>
    </div>
  );
}

export function SupplierCard({ card }: { card: EntityCardData }): ReactElement {
  const certs = card.certs ?? [];
  return (
    <div className="rfq-fade-in w-full max-w-[92%] self-start overflow-hidden rounded-xl border border-line bg-surface transition-all hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-md">
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
