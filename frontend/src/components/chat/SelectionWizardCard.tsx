/** SelectionWizardCard — AI 在对话中下发的选型表单卡（菜单「选型 → 选型向导」触发）。
 *  v2：按厂商选型七要素设计（真空度/抽速/气体成分/污染敏感度/场景/预算）：
 *  - 抽速/极限真空带单位切换与自动换算提示（1 m³/h≈0.278 L/s；1 mbar=100 Pa=0.75 Torr）
 *  - 被抽介质（气体成分，最关键选型因子）与特殊要求（污染敏感度等）为多选标签组
 *  - 「填入示例」一键预填演示工况；提交后卡片显示工况摘要并随 ChatMessage 持久化 */

import { useState, type ReactElement } from "react";
import { SlidersHorizontal } from "lucide-react";

const SCENES: string[] = ["实验室", "真空镀膜", "化工过程", "半导体制造", "食品包装", "真空热处理", "医疗设备"];
// 被抽气体成分（选型最关键且最常被忽略的因子，决定泵型与材质）
const MEDIA: string[] = ["清洁空气", "水蒸气", "粉尘颗粒", "腐蚀性气体", "有机溶剂", "惰性气体"];
// 特殊要求（污染敏感度 / 环境 / 运行制度）
const REQUIREMENTS: string[] = ["无油洁净", "低噪音", "耐腐蚀", "连续运行"];

const SPEED_UNITS = ["m³/h", "L/s"] as const;
const VACUUM_UNITS = ["Pa", "mbar", "Torr"] as const;

interface SelectionWizardCardProps {
  submitted: boolean;
  summary?: string;
  disabled: boolean; // busy（AI 回答中）时禁填，防打断流式
  onSubmit: (message: string) => void;
}

const inputClass =
  "w-full rounded-lg border border-line bg-surface px-3 py-2.5 text-sm text-ink placeholder:text-ink-muted focus:border-primary focus:outline-none disabled:opacity-50";
const labelClass = "mb-1 block text-xs font-medium text-ink-secondary";
const hintClass = "mt-1 block text-[11px] text-ink-muted";

function pill(active: boolean): string {
  return `rounded-full border px-3 py-1.5 text-xs transition-colors disabled:opacity-50 ${
    active ? "border-primary bg-primary-light font-medium text-primary" : "border-line text-ink-muted hover:border-primary hover:text-ink"
  }`;
}

export function SelectionWizardCard({ submitted, summary, disabled, onSubmit }: SelectionWizardCardProps): ReactElement {
  const [speed, setSpeed] = useState("");
  const [speedUnit, setSpeedUnit] = useState<(typeof SPEED_UNITS)[number]>("m³/h");
  const [vacuum, setVacuum] = useState("");
  const [vacuumUnit, setVacuumUnit] = useState<(typeof VACUUM_UNITS)[number]>("Pa");
  const [media, setMedia] = useState<string[]>([]);
  const [reqs, setReqs] = useState<string[]>([]);
  const [scene, setScene] = useState("");
  const [budget, setBudget] = useState("");

  const locked = submitted || disabled;
  const hasInput =
    speed.trim() !== "" || vacuum.trim() !== "" || scene !== "" || media.length > 0 || reqs.length > 0 || budget.trim() !== "";
  const canSubmit = !submitted && !disabled && hasInput;

  // 单位自动换算提示（行业换算：1 m³/h ≈ 0.278 L/s；1 mbar = 100 Pa = 0.75 Torr）
  const speedNum = Number(speed);
  const speedHint =
    speed.trim() !== "" && Number.isFinite(speedNum) && speedNum > 0
      ? speedUnit === "m³/h"
        ? `≈ ${(speedNum / 3.6).toFixed(1)} L/s`
        : `≈ ${(speedNum * 3.6).toFixed(1)} m³/h`
      : "";
  const vacuumNum = Number(vacuum);
  const vacuumHint =
    vacuum.trim() !== "" && Number.isFinite(vacuumNum) && vacuumNum > 0
      ? vacuumUnit === "Pa"
        ? `≈ ${(vacuumNum / 100).toFixed(4)} mbar`
        : vacuumUnit === "mbar"
          ? `≈ ${(vacuumNum * 100).toFixed(2)} Pa`
          : `≈ ${(vacuumNum * 133.322).toFixed(3)} Pa`
      : "";

  const toggle = (list: string[], set: (v: string[]) => void, item: string): void => {
    set(list.includes(item) ? list.filter((x) => x !== item) : [...list, item]);
  };

  const fillExample = (): void => {
    if (locked) return;
    setSpeed("100");
    setSpeedUnit("m³/h");
    setVacuum("0.01");
    setVacuumUnit("Pa");
    setMedia(["水蒸气"]);
    setReqs(["无油洁净", "低噪音"]);
    setScene("真空镀膜");
    setBudget("5");
  };

  const submit = (): void => {
    if (!canSubmit) return;
    const parts: string[] = [];
    if (speed.trim()) parts.push(`抽速 ${speed.trim()} ${speedUnit}`);
    if (vacuum.trim()) parts.push(`极限真空 ${vacuum.trim()} ${vacuumUnit}`);
    if (scene) parts.push(`用于${scene}`);
    if (media.length > 0) parts.push(`被抽介质为${media.join("、")}`);
    if (reqs.length > 0) parts.push(`要求${reqs.join("、")}`);
    if (budget.trim()) parts.push(`预算 ${budget.trim()} 万元以内`);
    onSubmit(`帮我选型一台真空泵：${parts.join("，")}，请推荐合适的产品。`);
  };

  if (submitted) {
    return (
      <div className="ml-8 max-w-lg self-start rounded-xl border border-line bg-surface p-4">
        <p className="flex items-center gap-2 text-sm font-medium text-ink">
          <SlidersHorizontal className="h-4 w-4 text-primary" />
          选型表单已提交
        </p>
        {summary && <p className="mt-1.5 text-xs leading-relaxed text-ink-muted">{summary}</p>}
        <p className="mt-1.5 text-xs text-ink-muted">AI 正在按工况为您匹配产品，可查看下方结果。</p>
      </div>
    );
  }

  return (
    <div className="ml-8 max-w-lg self-start rounded-xl border border-line bg-surface p-4">
      <div className="flex items-center justify-between gap-2">
        <p className="flex items-center gap-2 text-sm font-medium text-ink">
          <SlidersHorizontal className="h-4 w-4 text-primary" />
          选型表单
          <span className="text-xs font-normal text-ink-muted">按厂商选型七要素，至少填一项</span>
        </p>
        <button
          type="button"
          onClick={fillExample}
          disabled={locked}
          className="shrink-0 text-xs text-primary transition-colors hover:underline disabled:opacity-50"
        >
          填入示例
        </button>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2.5">
        <label className="block">
          <span className={labelClass}>抽速</span>
          <div className="flex gap-1.5">
            <input
              value={speed}
              onChange={(e) => setSpeed(e.target.value)}
              inputMode="decimal"
              placeholder="如 100"
              disabled={locked}
              className={inputClass}
            />
            <select
              value={speedUnit}
              onChange={(e) => setSpeedUnit(e.target.value as (typeof SPEED_UNITS)[number])}
              disabled={locked}
              className="w-20 shrink-0 rounded-lg border border-line bg-surface px-1.5 py-2.5 text-xs text-ink focus:border-primary focus:outline-none disabled:opacity-50"
            >
              {SPEED_UNITS.map((u) => (
                <option key={u} value={u}>
                  {u}
                </option>
              ))}
            </select>
          </div>
          <span className={hintClass}>{speedHint || "抽气快慢"}</span>
        </label>
        <label className="block">
          <span className={labelClass}>极限真空</span>
          <div className="flex gap-1.5">
            <input
              value={vacuum}
              onChange={(e) => setVacuum(e.target.value)}
              inputMode="decimal"
              placeholder="如 0.01"
              disabled={locked}
              className={inputClass}
            />
            <select
              value={vacuumUnit}
              onChange={(e) => setVacuumUnit(e.target.value as (typeof VACUUM_UNITS)[number])}
              disabled={locked}
              className="w-20 shrink-0 rounded-lg border border-line bg-surface px-1.5 py-2.5 text-xs text-ink focus:border-primary focus:outline-none disabled:opacity-50"
            >
              {VACUUM_UNITS.map((u) => (
                <option key={u} value={u}>
                  {u}
                </option>
              ))}
            </select>
          </div>
          <span className={hintClass}>{vacuumHint || "数值越小真空度越高"}</span>
        </label>
      </div>

      <div className="mt-3">
        <span className={labelClass}>被抽介质（可多选）</span>
        <div className="flex flex-wrap gap-1.5">
          {MEDIA.map((item) => (
            <button key={item} type="button" disabled={locked} onClick={() => toggle(media, setMedia, item)} className={pill(media.includes(item))}>
              {item}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-3">
        <span className={labelClass}>特殊要求（可多选）</span>
        <div className="flex flex-wrap gap-1.5">
          {REQUIREMENTS.map((item) => (
            <button key={item} type="button" disabled={locked} onClick={() => toggle(reqs, setReqs, item)} className={pill(reqs.includes(item))}>
              {item}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-3">
        <span className={labelClass}>应用场景（点选）</span>
        <div className="flex flex-wrap gap-1.5">
          {SCENES.map((item) => (
            <button key={item} type="button" disabled={locked} onClick={() => setScene(scene === item ? "" : item)} className={pill(scene === item)}>
              {item}
            </button>
          ))}
        </div>
      </div>

      <label className="mt-3 block">
        <span className={labelClass}>预算（可选）</span>
        <div className="flex items-center gap-2">
          <input
            value={budget}
            onChange={(e) => setBudget(e.target.value)}
            inputMode="decimal"
            placeholder="如 5"
            disabled={locked}
            className={inputClass}
          />
          <span className="shrink-0 text-xs text-ink-muted">万元以内</span>
        </div>
      </label>

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
