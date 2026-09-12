/** Widget bootstrap (zero-intrusion embed, ADR-008):
 *  1) reads data-endpoint from the script tag (or window.RFQ_ENDPOINT);
 *  2) creates #rfq-copilot-widget root at body end (host DOM untouched);
 *  3) mounts ChatWidget; host site needs zero React knowledge.
 * Style isolation: widget styles ship in the bundle and are scoped by the
 * rfq- prefixed tokens; host site CSS cannot leak in via Shadow-less mount.
 */

import { createRoot } from "react-dom/client";
import { ChatWidget } from "../components/chat/ChatWidget";

function mount(): void {
  const script =
    document.currentScript ??
    (document.querySelector('script[src*="rfq-chat.js"]') as HTMLScriptElement | null);
  const endpoint = script?.dataset.endpoint ?? "";

  let host = document.getElementById("rfq-copilot-widget");
  if (host === null) {
    host = document.createElement("div");
    host.id = "rfq-copilot-widget";
    document.body.appendChild(host);
  }

  (window as unknown as { RFQ_ENDPOINT?: string }).RFQ_ENDPOINT = endpoint;
  const root = createRoot(host);
  root.render(<ChatWidget />);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", mount);
} else {
  mount();
}

