import { describe, expect, it } from "vitest";

import { toEntityCard } from "../cardMapper";

describe("toEntityCard — 审查 R1 回归防线", () => {
  it("产品卡：name/supplier/price/specs 全映射", () => {
    const card = toEntityCard({
      kind: "product",
      name: "贝克 KVT 3.100 无油旋片真空泵",
      supplier: "示例真空装备（山东）有限公司",
      price: "可询价",
      url: "/products/evs-950",
      specs: { 抽速: "108 m³/h" },
    });
    expect(card.kind).toBe("product");
    expect(card.name).toBe("贝克 KVT 3.100 无油旋片真空泵");
    expect(card.supplier).toBe("示例真空装备（山东）有限公司");
    expect(card.specs).toEqual({ 抽速: "108 m³/h" });
  });

  it("方案卡：title 兜底到 name + 痛点/拓扑/供应商", () => {
    const card = toEntityCard({
      kind: "solution",
      title: "食品加工真空系统方案",
      industry: "食品加工",
      pain_points: [{ title: "污染风险", desc: "油污回流" }],
      topology: "旋片泵 → 过滤 → 包装线",
      suppliers: ["A 公司", "B 公司"],
      url: "/solutions/shipin",
    });
    expect(card.name).toBe("食品加工真空系统方案"); // R1 核心：title→name 兜底
    expect(card.title).toBe("食品加工真空系统方案");
    expect(card.industry).toBe("食品加工");
    expect(card.pain_points).toHaveLength(1);
    expect(card.topology).toContain("旋片泵");
    expect(card.suppliers).toEqual(["A 公司", "B 公司"]);
  });

  it("案例卡：metrics/has_whitepaper/customer 保留", () => {
    const card = toEntityCard({
      kind: "case",
      title: "某头部电池企业真空系统",
      industry: "锂电池",
      customer: "某头部企业",
      metrics: [{ label: "不良率", actual: "-60", unit: "%" }],
      has_whitepaper: true,
      url: "/cases/x",
    });
    expect(card.metrics).toBeDefined();
    expect(card.metrics?.[0]?.actual).toBe("-60");
    expect(card.has_whitepaper).toBe(true);
    expect(card.customer).toBe("某头部企业");
    expect(card.name).toBe("某头部电池企业真空系统");
  });

  it("询盘状态卡：inquiry_id/status_text/quote_count 保留", () => {
    const card = toEntityCard({
      kind: "inquiry_status",
      title: "AI询盘-sess_abc",
      inquiry_id: 12,
      status_text: "待报价",
      quote_count: 0,
      created_at: "2026-09-16T12:00:00+00:00",
    });
    expect(card.inquiry_id).toBe("12"); // 数值统一转字符串
    expect(card.status_text).toBe("待报价");
    expect(card.quote_count).toBe(0);
  });

  it("缺字段不产生 undefined 崩溃（空事件容错）", () => {
    const card = toEntityCard({ kind: "product" });
    expect(card.name).toBe("");
    expect(card.supplier).toBeUndefined();
    expect(card.metrics).toBeUndefined();
  });
});
