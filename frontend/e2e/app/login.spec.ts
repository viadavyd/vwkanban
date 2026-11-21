import { expect, test } from "@playwright/test";

const username = process.env.ADMIN_USERNAME ?? "admin";
const password = process.env.ADMIN_PASSWORD ?? "change-me-too";

// Keyboard only: no clicks and no fill(); every input is typed keys, Tab and Enter.
test("keyboard-only login, with a wrong password first", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { name: "Log in" })).toBeVisible();
  await expect(page.getByLabel("Username")).toBeFocused();

  await page.keyboard.type(username);
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("Password")).toBeFocused();
  await page.keyboard.type("definitely-wrong");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("alert")).toHaveText(/invalid username or password/i);
  await expect(page).toHaveURL(/\/login$/);

  // The password is cleared and focus stays in it: retype and submit.
  await expect(page.getByLabel("Password")).toBeFocused();
  await expect(page.getByLabel("Password")).toHaveValue("");
  await page.keyboard.type(password);
  await page.keyboard.press("Enter");

  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByTestId("username")).toHaveText(username);

  // The session survives a reload, and /login goes back to the dashboard.
  await page.reload();
  await expect(page.getByTestId("username")).toHaveText(username);
  await page.goto("/login");
  await expect(page).toHaveURL(/\/$/);

  const cookie = (await page.context().cookies()).find((c) => c.name === "vwk_session");
  expect(cookie).toMatchObject({ httpOnly: true, sameSite: "Lax" });
});
