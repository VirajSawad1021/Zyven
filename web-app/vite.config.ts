import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// In dev, proxy the API to the FastAPI board (`python -m zyven.cli board --port 8765`).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
  build: { outDir: "dist", sourcemap: false },
});
