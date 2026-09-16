/**
 * inquiryReducer — 询盘确认卡四态状态机（纯函数，UI 解耦）。
 *
 * 状态转移图（企业级约束：非法转移一律拒绝并保持原态）：
 *   editing --CONFIRM--> submitting --CREATED--> sent
 *                              |--ERROR----> error
 *   error   --RETRY----> submitting
 *   editing --CANCEL--> (移除卡片)
 *   submitting/sent/error 期间忽略 CANCEL/CONFIRM 等越权动作。
 *
 * 设计参考：uxpatterns.dev "可交互卡必须状态闭环" + Carbon 结构化响应锁定原则。
 * 测试：inquiryReducer.test.ts 覆盖全部合法路径 + 非法转移拒绝。
 */

export type InquiryPhase = "editing" | "submitting" | "sent" | "error";

export interface InquiryCardState {
  phase: InquiryPhase;
  confirmId: string;
  inquiryId: string | null;
  /** submitting/sent/error 态锁定：按钮禁用依据 */
  locked: boolean;
}

export type InquiryAction =
  | { type: "CONFIRM" }
  | { type: "CANCEL" }
  | { type: "CREATED"; inquiryId: string }
  | { type: "SUBMIT_ERROR" }
  | { type: "RETRY" };

export function createInquiryCardState(confirmId: string, inquiryId: string | null = null): InquiryCardState {
  return { phase: "editing", confirmId, inquiryId, locked: false };
}

export function inquiryReducer(state: InquiryCardState, action: InquiryAction): InquiryCardState {
  switch (action.type) {
    case "CONFIRM":
      if (state.phase !== "editing") return state;
      return { ...state, phase: "submitting", locked: true };
    case "CANCEL":
      if (state.phase !== "editing") return state;
      return state; // 调用方据此决定是否移除卡片（reducer 保持纯函数）
    case "CREATED":
      if (state.phase !== "submitting") return state;
      return { ...state, phase: "sent", inquiryId: action.inquiryId, locked: true };
    case "SUBMIT_ERROR":
      if (state.phase !== "submitting") return state;
      return { ...state, phase: "error", locked: false };
    case "RETRY":
      if (state.phase !== "error") return state;
      return { ...state, phase: "submitting", locked: true };
    default:
      return state;
  }
}
