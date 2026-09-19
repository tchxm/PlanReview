import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { resolve } from "node:path";

// Development: Vite serves the UI on 127.0.0.1:5173 and proxies the API to
// FastAPI on 127.0.0.1:8000. Override the target with PLANREVIEW_API_URL.
const api = process.env.PLANREVIEW_API_URL || "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { rollupOptions: { input: { main: resolve(__dirname, "index.html"), console: resolve(__dirname, "console.html") } } },
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: { "/api": api, "/docs": api, "/openapi.json": api },
  },
  test: { environment: "node", include: ["src/**/*.test.js"] },
});
