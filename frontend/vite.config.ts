/// <reference types="vitest/config" />
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";

export default defineConfig(({ mode }) => {
  const spike = mode === "spike";
  return {
    plugins: [svelte()],
    server: {
      proxy: { "/api": { target: "http://127.0.0.1:8000", ws: true } },
    },
    build: {
      // The production build ships only index.html; the vim spike builds separately.
      outDir: spike ? "dist-spike" : "dist",
      rollupOptions: spike ? { input: { spike: "spike.html" } } : undefined,
    },
    test: { include: ["tests/**/*.test.ts"], environment: "node" },
  };
});
