import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// /api and /health go to FastAPI, so the browser sees one origin in dev and the
// OAuth redirect does not care which port it came from.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5180,
    strictPort: true,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
      "/health": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
});
