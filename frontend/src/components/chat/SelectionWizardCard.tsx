/** SelectionWizardCard — AI 在对话中下发的选型表单卡（菜单「选型 → 选型向导」触发）。
 *  填工况（抽速/极限真空/应用场景，至少一项）→ 组装完整工况消息发送 → 引擎意图抽取
 *  走 spec_match_flow 出产品卡。提交后卡片转已提交态并随 ChatMessage 持久化。
 *  交互：字段带标签、应用场景为点选式标签组（可多想再点取消），整体宽幅大字段。 */

import { useState, type ReactElement } from "react";
import { SlidersHorizontal } from "lucide-react";

// 选型向导的应用场景预设（覆盖真空设备主流行业）
const SCENES: string[] = ["实验室", "真空镀膜", "化工过程", "半导体制造", "食品包装", "真空热处理", "医疗设备"];

interface SelectionWizardCardProps {
  submitted: boolean;
  disabled: boolean; // busy（AI 回答中）时禁填，防打断流式
  onSubmit: (message: string) => void;
}

const inputClass =
  "w-full rounded-lg border border-line bg-surface px-3 py-2.5 text-sm text-ink placeholder:text-ink-muted focus:border-primary focus:outline-none disabled:opacity-50";

export function SelectionWizardCard({ submitted, disabled, onSubmit }: SelectionWizardCardProps): ReactElement {
  const [speed, setSpeed] = useState("");
  const [vacuum, setVacuum] = useState("");
  const [scene, setScene] = useState("");

  const locked = submitted || disabled;
  const canSubmit = !submitted && !disabled && (speed.trim() !== "" || vacuum.trim() !== "" || scene !== "");

  const submit = (): void => {
    if (!canSubmit) return;
    const parts: string[] = [];
    if (speed.trim()) parts.push(`抽速 ${speed.trim()} m³/h`);
    if (vacuum.trim()) parts.push(`极限真空 ${vacuum.trim()} Pa`);
    if (scene) parts.push(`用于${scene}`);
    onSubmit(`帮我选型一台真空泵：${parts.join("，")}，请推荐合适的产品。`);
  };

  if (submitted) {
    return (
      <div className="ml-8 flex max-w-lg items-center gap-2 self-start rounded-xl border border-line bg-surface px-4 py-3 text-sm text-ink-muted">
        <SlidersHorizontal className="h-4 w-4 shrink-0 text-primary" />
        选型表单已提交，AI 正在按工况为您匹配产品（可查看下方结果）
      </div>
    );
  }

  return (
    <div className="ml-8 max-w-lg self-start rounded-xl border border-line bg-surface p-4">
      <p className="flex items-center gap-2 text-sm font-medium text-ink">
        <SlidersHorizontal className="h-4 w-4 text-primary" />
        选型表单
        <span className="text-xs font-normal text-ink-muted">填工况找产品，至少填一项</span>
      </p>
      <div className="mt-3 grid grid-cols-2 gap-2.5">
        <label className="block">
          <span className="mb-1 block text-xs text-ink-muted">抽速</span>
          <input
            value={speed}
            onChange={(e) => setSpeed(e.target.value)}
            inputMode="decimal"
            placeholder="如 100"
            disabled={locked}
            className={inputClass}
          />
          <span className="mt-1 block text-[11px] text-ink-muted">单位 m³/h</span>
        </label>
        <label className="block">
          <span className="mb-1 block text-xs text-ink-muted">极限真空</span>
          <input
            value={vacuum}
            onChange={(e) => setVacuum(e.target.value)}
            inputMode="decimal"
            placeholder="如 0.01"
            disabled={locked}
            className={inputClass}
          />
          <span className="mt-1 block text-[11px] text-ink-muted">单位 Pa，数值越小真空度越高</span>
        </label>
      </div>
      <div className="mt-3">
        <span className="mb-1.5 block text-xs text-ink-muted">应用场景（可选，点选）</span>
        <div className="flex flex-wrap gap-1.5">
          {SCENES.map((item) => {
            const active = scene === item;
            return (
              <button
                key={item}
                type="button"
                disabled={locked}
                onClick={() => setScene(active ? "" : item)}
                className={`rounded-full border px-3 py-1.5 text-xs transition-colors disabled:opacity-50 ${
                  active
                    ? "border-primary bg-primary-light font-medium text-primary"
                    : "border-line text-ink-muted hover:border-primary hover:text-ink"
                }`}
              >
                {item}
              </button>
            );
          })}
        </div>
      </div>
      <button
        type="button"
        onClick={submit}
        disabled={!canSubmit}
        className="mt-4 w-full rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-primary-hover disabled:bg-line disabled:text-ink-muted"
      >
        一键找产品
      </button>
    </div>
  );
}
