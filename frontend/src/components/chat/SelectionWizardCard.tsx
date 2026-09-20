/** SelectionWizardCard — AI 在对话中下发的选型表单卡（菜单「选型 → 选型向导」触发）。
 *  填工况（抽速/极限真空/应用场景，至少一项）→ 组装完整工况消息发送 → 引擎意图抽取
 *  走 spec_match_flow 出产品卡。提交后卡片转已提交态并随 ChatMessage 持久化。 */

import { useState, type ReactElement } from "react";
import { SlidersHorizontal } from "lucide-react";

// 选型向导的应用场景预设（覆盖真空设备主流行业）
const SCENES: string[] = ["实验室", "真空镀膜", "化工过程", "半导体制造", "食品包装", "真空热处理", "医疗设备"];

interface SelectionWizardCardProps {
  submitted: boolean;
  disabled: boolean; // busy（AI 回答中）时禁填，防打断流式
  onSubmit: (message: string) => void;
}

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
      <div className="ml-8 flex max-w-md items-center gap-2 self-start rounded-xl border border-line bg-surface px-3 py-2.5 text-xs text-ink-muted">
        <SlidersHorizontal className="h-3.5 w-3.5 text-primary" />
        选型表单已提交，AI 正在按工况为您匹配产品（可查看下方结果）
      </div>
    );
  }

  return (
    <div className="ml-8 max-w-md self-start rounded-xl border border-line bg-surface p-3">
      <p className="flex items-center gap-1.5 text-xs font-medium text-ink">
        <SlidersHorizontal className="h-3.5 w-3.5 text-primary" />
        选型表单
        <span className="font-normal text-ink-muted">填工况找产品，至少填一项</span>
      </p>
      <div className="mt-2 flex gap-1.5">
        <input
          value={speed}
          onChange={(e) => setSpeed(e.target.value)}
          inputMode="decimal"
          placeholder="抽速 m³/h"
          disabled={locked}
          className="w-full rounded-lg border border-line bg-surface px-2 py-1.5 text-xs text-ink placeholder:text-ink-muted focus:border-primary focus:outline-none disabled:opacity-50"
        />
        <input
          value={vacuum}
          onChange={(e) => setVacuum(e.target.value)}
          inputMode="decimal"
          placeholder="极限真空 Pa"
          disabled={locked}
          className="w-full rounded-lg border border-line bg-surface px-2 py-1.5 text-xs text-ink placeholder:text-ink-muted focus:border-primary focus:outline-none disabled:opacity-50"
        />
      </div>
      <select
        value={scene}
        onChange={(e) => setScene(e.target.value)}
        disabled={locked}
        className="mt-1.5 w-full rounded-lg border border-line bg-surface px-2 py-1.5 text-xs text-ink focus:border-primary focus:outline-none disabled:opacity-50"
      >
        <option value="">应用场景（可选）</option>
        {SCENES.map((item) => (
          <option key={item} value={item}>
            {item}
          </option>
        ))}
      </select>
      <button
        type="button"
        onClick={submit}
        disabled={!canSubmit}
        className="mt-2 w-full rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-primary-hover disabled:bg-line disabled:text-ink-muted"
      >
        一键找产品
      </button>
    </div>
  );
}
