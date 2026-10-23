import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// All app URLs are relative (/api/..., /ws/stream), so the same build works when FastAPI
// serves it (Phase 6). In dev, Vite forwards them to the backend. Use 127.0.0.1, not
// localhost: WebSocket connections hang on IPv6 ::1 on the dev machine.
const BACKEND = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  base: "./",
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: BACKEND, changeOrigin: true },
      "/ws": { target: BACKEND, ws: true, changeOrigin: true },
    },
  },
  // One local bundle (React + Recharts) is fine for an offline laptop app.
  build: { chunkSizeWarningLimit: 800 },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
