import { expect, test as setup, type APIRequestContext } from "@playwright/test";
import { BOB, BOB_STATE, ORIGIN, STATE } from "./helpers";

// One login per user for the board specs (login is rate-limited to 5/min per IP): the
// admin for most specs, and a second user (BOB_USERNAME / BOB_PASSWORD, created with
// `vwk user create`) for the two-user real-time specs.
async function logIn(request: APIRequestContext, username: string, password: string, path: string) {
  const r = await request.post("/api/auth/login", {
    data: { username, password },
    headers: { Origin: ORIGIN },
  });
  expect(r.status(), `log in ${username}: ${await r.text()}`).toBe(200);
  await request.storageState({ path });
}

setup("log in once", async ({ request }) => {
  await logIn(
    request,
    process.env.ADMIN_USERNAME ?? "admin",
    process.env.ADMIN_PASSWORD ?? "change-me-too",
    STATE,
  );
});

setup("log in the second user", async ({ playwright, baseURL }) => {
  const password = process.env.BOB_PASSWORD;
  expect(password, "set BOB_PASSWORD (and create the user: vwk user create bob)").toBeTruthy();
  const request = await playwright.request.newContext({ baseURL });
  await logIn(request, BOB, password!, BOB_STATE);
  await request.dispose();
});
