import { defineConfig, devices } from "@playwright/test";

// App e2e against a running stack (compose), e.g.
//   VWK_BASE_URL=http://vwk.test ADMIN_USERNAME=admin ADMIN_PASSWORD=... npm run e2e:app
// VWK_BASE_URL must match the stack's PUBLIC_URL (the API checks Origin).
// VWK_PERF_ENFORCE=1 makes board-perf.spec.ts fail on a missed §7 target (report-only
// otherwise, as shared CI runners are noisy).
export default defineConfig({
  testDir: "e2e/app",
  reporter: [["list"]],
  // Login is rate-limited per IP (5/min), so keep runs serial and without retries. The
  // board specs share one login (auth.setup.ts → STATE); only the login and dashboard
  // specs log in themselves.
  workers: 1,
  retries: 0,
  use: { baseURL: process.env.VWK_BASE_URL ?? "http://localhost" },
  projects: [
    { name: "setup", testMatch: /\.setup\.ts$/ },
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
      dependencies: ["setup"],
    },
  ],
});
