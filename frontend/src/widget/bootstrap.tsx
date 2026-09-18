/** Widget bootstrap (ADR-008 + T-012 Shadow DOM isolation):
 *  1) reads data-endpoint from the script tag (or window.RFQ_ENDPOINT);
 *  2) creates #rfq-copilot-widget host at body end and attaches a Shadow Root;
 *  3) injects the build-time CSS (?inline) as a <style> INSIDE the shadow root —
 *     host site CSS cannot leak in, widget styles cannot leak out;
 *  4) mounts ChatWidget inside the shadow root (host needs zero React knowledge).
 */

import { createRoot } from "react-dom/client";
import { ChatWidget } from "../components/chat/ChatWidget";
import widgetCss from "../styles/globals.css?inline";

function mount(): void {
  const script =
    document.currentScript ??
    (document.querySelector('script[src*="rfq-chat.js"]') as HTMLScriptElement | null);
  const endpoint = script?.dataset.endpoint ?? "";
  // E1 鉴权桥：宿主站点 blade 随登录态注入
  //   data-user-ref（用户 id）+ data-ai-ticket（HMAC 短时票据）→ sessions 验签
  const userRef = script?.dataset.userRef ?? "";
  const aiTicket = script?.dataset.aiTicket ?? "";
  // 演示/生产模式：data-widget-mode="demo" 时显示分级访问演示条（假登录）；
  // 缺省 production——游客态渲染可关闭的登录引导（跳 data-login-url）
  const widgetMode = script?.dataset.widgetMode === "demo" ? "demo" : "production";
  const loginUrl = script?.dataset.loginUrl ?? "";

  let host = document.getElementById("rfq-copilot-widget");
  if (host === null) {
    host = document.createElement("div");
    host.id = "rfq-copilot-widget";
    document.body.appendChild(host);
  }
  if (host.shadowRoot) return; // 防重复注入

  const shadow = host.attachShadow({ mode: "open" });
  const style = document.createElement("style");
  style.textContent = widgetCss;
  shadow.appendChild(style);

  const container = document.createElement("div");
  container.className = "rfq-root";
  shadow.appendChild(container);

  (window as unknown as { RFQ_ENDPOINT?: string }).RFQ_ENDPOINT = endpoint;
  createRoot(container).render(
    <ChatWidget initialUserRef={userRef} aiTicket={aiTicket} widgetMode={widgetMode} loginUrl={loginUrl} />,
  );
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", mount);
} else {
  mount();
}
