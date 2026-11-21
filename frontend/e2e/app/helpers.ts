import { expect, type Page } from "@playwright/test";

export const BASE_URL = process.env.VWK_BASE_URL ?? "http://localhost";
/** State-changing API calls must send the stack's own origin. */
export const ORIGIN = new URL(BASE_URL).origin;
/** Login state written by auth.setup.ts. */
export const STATE = "e2e/.auth/state.json";
/** The admin's username (the user in STATE). */
export const ADMIN = process.env.ADMIN_USERNAME ?? "admin";
/** The second user (for two-user specs), and their login state. */
export const BOB = process.env.BOB_USERNAME ?? "bob";
export const BOB_STATE = "e2e/.auth/bob.json";

export const column = (page: Page, name: string) => page.getByRole("region", { name });

/** The tile whose title is exactly `title`. */
export const card = (page: Page, title: string) =>
  page.locator("[data-card]").filter({ has: page.getByText(title, { exact: true }) });

/** Waits until a column shows exactly these card titles, in order. (A web-first assertion:
 * after a reload the board renders asynchronously, so a one-shot read can see no cards.) */
export async function expectTitles(page: Page, name: string, titles: string[]) {
  await expect(column(page, name).locator("[data-card] .title")).toHaveText(titles);
}

export async function expectSelected(page: Page, title: string) {
  await expect(card(page, title)).toHaveAttribute("aria-selected", "true");
  await expect(page.locator('[data-card][aria-selected="true"]')).toHaveCount(1);
}

/** Waits until the board is live and every op it sent is answered (the top bar's sync
 * dot). Use after a key that sends an op, and after a reload before reading the board. */
export async function settled(page: Page) {
  const sync = page.getByTestId("sync");
  await expect(sync).toHaveAttribute("data-state", "live");
  await expect(sync).toHaveAttribute("data-pending", "0");
}

export const mode = (page: Page) => page.getByTestId("mode");
export const cardView = (page: Page) => page.getByTestId("card-view");

/** `a` (or `A`) on the board: card mode opens with the title in INSERT; type it, `Enter`
 * saves it (the card is created) and leaves the field, `Esc` closes the card. */
export async function newCard(page: Page, title: string, key: "a" | "A" = "a") {
  await page.keyboard.press(key);
  await expect(cardView(page)).toBeVisible();
  await page.keyboard.type(title);
  await page.keyboard.press("Enter");
  await expect(mode(page)).toHaveText("-- CARD --");
  await page.keyboard.press("Escape");
  await expect(cardView(page)).toHaveCount(0);
  await expectSelected(page, title);
}
