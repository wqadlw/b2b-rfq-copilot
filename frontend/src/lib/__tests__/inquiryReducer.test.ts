import { describe, expect, it } from "vitest";
import { createInquiryCardState, inquiryReducer } from "@/lib/inquiryReducer";

describe("inquiryReducer 状态机", () => {
  it("editing --CONFIRM--> submitting 并锁定", () => {
    const s = inquiryReducer(createInquiryCardState("c1"), { type: "CONFIRM" });
    expect(s.phase).toBe("submitting");
    expect(s.locked).toBe(true);
  });

  it("submitting --CREATED--> sent 记录编号", () => {
    let s = inquiryReducer(createInquiryCardState("c1"), { type: "CONFIRM" });
    s = inquiryReducer(s, { type: "CREATED", inquiryId: "INQ-1" });
    expect(s.phase).toBe("sent");
    expect(s.inquiryId).toBe("INQ-1");
  });

  it("submitting --SUBMIT_ERROR--> error 解锁可重试", () => {
    let s = inquiryReducer(createInquiryCardState("c1"), { type: "CONFIRM" });
    s = inquiryReducer(s, { type: "SUBMIT_ERROR" });
    expect(s.phase).toBe("error");
    expect(s.locked).toBe(false);
  });

  it("error --RETRY--> submitting", () => {
    let s = inquiryReducer(createInquiryCardState("c1"), { type: "CONFIRM" });
    s = inquiryReducer(s, { type: "SUBMIT_ERROR" });
    s = inquiryReducer(s, { type: "RETRY" });
    expect(s.phase).toBe("submitting");
  });

  it("editing --CANCEL--> 原态（移除决定权在调用方）", () => {
    const s0 = createInquiryCardState("c1");
    const s = inquiryReducer(s0, { type: "CANCEL" });
    expect(s).toBe(s0);
  });

  it("拒绝非法转移：sent 后 CONFIRM/RETRY 无效", () => {
    let s = inquiryReducer(createInquiryCardState("c1"), { type: "CONFIRM" });
    s = inquiryReducer(s, { type: "CREATED", inquiryId: "INQ-1" });
    const sent = s;
    expect(inquiryReducer(sent, { type: "CONFIRM" })).toBe(sent);
    expect(inquiryReducer(sent, { type: "RETRY" })).toBe(sent);
    expect(inquiryReducer(sent, { type: "SUBMIT_ERROR" })).toBe(sent);
  });

  it("拒绝非法转移：editing 直接 CREATED 无效", () => {
    const s0 = createInquiryCardState("c1");
    const s = inquiryReducer(s0, { type: "CREATED", inquiryId: "X" });
    expect(s.phase).toBe("editing");
  });
});
