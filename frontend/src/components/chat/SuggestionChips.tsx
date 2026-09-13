/** SuggestionChips — 空态引导（形态参考 ai-chatbot ai-elements/Suggestion）。 */

import type { ReactElement } from "react";
import { Sparkles } from "lucide-react";

export function SuggestionChips({
  questions,
  onPick,
}: {
  questions: string[];
  onPick: (q: string) => void;
}): ReactElement {
  if (questions.length === 0) return <></>;
  return (
    <div className="flex flex-wrap gap-2">
      {questions.map((q) => (
        <button
          key={q}
          type="button"
          onClick={() => onPick(q)}
          className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-2.5 py-1.5 text-xs text-ink-secondary transition-colors hover:border-primary hover:text-primary"
        >
          <Sparkles className="h-3 w-3 text-accent" />
          {q}
        </button>
      ))}
    </div>
  );
}
