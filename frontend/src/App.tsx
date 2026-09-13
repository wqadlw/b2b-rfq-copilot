import type { ReactElement } from "react";
import { ChatWidget } from "./components/chat/ChatWidget";

export default function App(): ReactElement {
  return (
    <div className="min-h-screen bg-ink/[0.04] py-0 md:py-6">
      <div className="mx-auto max-w-2xl overflow-hidden border-line bg-surface shadow-sm md:rounded-2xl md:border">
        <ChatWidget />
      </div>
    </div>
  );
}
