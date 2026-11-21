import { defineConfig, devices } from "@playwright/test";

// App e2e against a running stack (compose), e.g.
//   VWK_BASE_URL=http://vwk.test ADMIN_USERNAME=admin ADMIN_PASSWORD=... npm run e2e:app
// VWK_BASE_URL must match the stack's PUBLIC_URL (the API checks Origin).
export default defineConfig({
  testDir: "e2e/app",
  reporter: [["list"]],
  // Login is rate-limited per IP (5/min), so keep runs serial and without retries.
  workers: 1,
  retries: 0,
  use: { baseURL: process.env.VWK_BASE_URL ?? "http://localhost" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
