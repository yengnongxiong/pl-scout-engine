/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The API base path the browser calls; the dev server forwards it to FastAPI (PRD §12).
const API_PREFIX = "/api";
const API_TARGET = process.env.SCOUT_API_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      [API_PREFIX]: {
        target: API_TARGET,
        changeOrigin: true,
        rewrite: (path) => path.slice(API_PREFIX.length) || "/",
      },
    },
  },
  preview: {
    port: 5173,
    strictPort: true,
    proxy: {
      [API_PREFIX]: {
        target: API_TARGET,
        changeOrigin: true,
        rewrite: (path) => path.slice(API_PREFIX.length) || "/",
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    restoreMocks: true,
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/api/schema.d.ts", "src/test/**", "src/main.tsx"],
    },
  },
});
