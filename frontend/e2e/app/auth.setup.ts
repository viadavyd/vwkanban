import { expect, test as setup } from "@playwright/test";
import { ORIGIN, STATE } from "./helpers";

// One login for the board specs (login is rate-limited to 5/min per IP).
setup("log in once", async ({ request }) => {
  const r = await request.post("/api/auth/login", {
    data: {
      username: process.env.ADMIN_USERNAME ?? "admin",
      password: process.env.ADMIN_PASSWORD ?? "change-me-too",
    },
    headers: { Origin: ORIGIN },
  });
  expect(r.status(), await r.text()).toBe(200);
  await request.storageState({ path: STATE });
});
