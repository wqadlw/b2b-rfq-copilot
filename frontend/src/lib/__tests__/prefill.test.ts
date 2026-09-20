/** prefillFromEvent 单测：主动触达 rfq:prefill 事件 detail 的安全提取（含防御路径）。 */

import { describe, expect, it } from "vitest";

import { prefillFromEvent } from "../utils";

describe("prefillFromEvent", () => {
  it("合法 message 返回去首尾空白的预填文案", () => {
    expect(prefillFromEvent("", { message: "  我想了解「XG-40」的参数  " })).toBe(
      "我想了解「XG-40」的参数",
    );
  });

  it("message 为空串/纯空白 → 返回 current（不覆盖输入框）", () => {
    expect(prefillFromEvent("已输入内容", { message: "" })).toBe("已输入内容");
    expect(prefillFromEvent("已输入内容", { message: "   " })).toBe("已输入内容");
  });

  it("message 非字符串（数字/对象/缺失）→ 返回 current", () => {
    expect(prefillFromEvent("cur", { message: 123 })).toBe("cur");
    expect(prefillFromEvent("cur", { message: { x: 1 } })).toBe("cur");
    expect(prefillFromEvent("cur", {})).toBe("cur");
  });

  it("detail 非对象（null/undefined/原始值）→ 返回 current", () => {
    expect(prefillFromEvent("cur", null)).toBe("cur");
    expect(prefillFromEvent("cur", undefined)).toBe("cur");
    expect(prefillFromEvent("cur", "txt")).toBe("cur");
  });

  it("超长文案截断到 200 字", () => {
    const long = "a".repeat(500);
    expect(prefillFromEvent("", { message: long })).toHaveLength(200);
  });
});
