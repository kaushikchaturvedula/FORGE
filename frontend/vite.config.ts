import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// FORGE field console. The realtime backend (FastAPI) is proxied so the browser
// can open a same-origin WebSocket to /ws during local development.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/ws": { target: "ws://localhost:8000", ws: true },
      "/api": { target: "http://localhost:8000", changeOrigin: true },
      "/cloud": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
