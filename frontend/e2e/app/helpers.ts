import { expect, type Page } from "@playwright/test";

export const BASE_URL = process.env.VWK_BASE_URL ?? "http://localhost";
/** State-changing API calls must send the stack's own origin. */
export const ORIGIN = new URL(BASE_URL).origin;
/** Login state written by auth.setup.ts. */
export const STATE = "e2e/.auth/state.json";

export const column = (page: Page, name: string) => page.getByRole("region", { name });

/** The tile whose title is exactly `title`. */
export const card = (page: Page, title: string) =>
  page.locator("[data-card]").filter({ has: page.getByText(title, { exact: true }) });

/** Titles of a column's cards, in order. */
export async function titles(page: Page, name: string): Promise<string[]> {
  return column(page, name).locator("[data-card] .title").allInnerTexts();
}

export async function expectSelected(page: Page, title: string) {
  await expect(card(page, title)).toHaveAttribute("aria-selected", "true");
  await expect(page.locator('[data-card][aria-selected="true"]')).toHaveCount(1);
}

/** Resolves when the response to the next op of `kind` arrives (ops are sent in order,
 * so every op queued before it is done too). */
export function opDone(page: Page, kind: string) {
  return page.waitForResponse(
    (r) => r.url().includes("/ops") && r.request().postDataJSON()?.op?.kind === kind,
  );
}
