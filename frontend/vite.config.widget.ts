/**
 * Widget IIFE build config: single-file rfq-chat.js, zero globals, React embedded.
 * Build: pnpm build:widget → dist-widget/rfq-chat.js
 */
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { resolve } from "path";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: { "process.env.NODE_ENV": '"production"' },
  build: {
    outDir: "dist-widget",
    lib: {
      entry: resolve(__dirname, "src/widget/bootstrap.tsx"),
      name: "rfqCopilotWidget",
      formats: ["iife"],
      fileName: () => "rfq-chat.js",
    },
    rollupOptions: {
      output: { extend: false, assetFileNames: "rfq-chat.[ext]" },
    },
  },
});
