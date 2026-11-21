import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  // e2e/app runs against a live stack via playwright.app.config.ts.
  testIgnore: "app/**",
  reporter: [["list"]],
  use: { baseURL: "http://127.0.0.1:4173" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command:
      "npm run spike:build && npx vite preview --mode spike --host 127.0.0.1 --port 4173 --strictPort",
    url: "http://127.0.0.1:4173/spike.html",
    reuseExistingServer: !process.env.CI,
  },
});
