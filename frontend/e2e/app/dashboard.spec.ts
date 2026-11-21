import { expect, test, type Page } from "@playwright/test";

const username = process.env.ADMIN_USERNAME ?? "admin";
const password = process.env.ADMIN_PASSWORD ?? "change-me-too";

// Keyboard only: no clicks and no fill(). The stack is persistent, so titles are unique.
const stamp = Date.now();
const title = `M2 e2e ${stamp}`;
const renamed = `M2 renamed ${stamp}`;

async function login(page: Page) {
  await page.goto("/");
  await expect(page.getByLabel("Username")).toBeFocused();
  await page.keyboard.type(username);
  await page.keyboard.press("Tab");
  await page.keyboard.type(password);
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("mode")).toHaveText("-- DASHBOARD --");
}

const tile = (page: Page, text: string) => page.getByRole("option").filter({ hasText: text });

test("keyboard-only dashboard: help, create, open, rename, delete, log out", async ({ page }) => {
  await login(page);

  // Help overlay, rendered from keymap.ts.
  await page.keyboard.press("?");
  const help = page.getByRole("dialog", { name: "Help" });
  await expect(help).toContainText("create a board");
  await expect(help).toContainText("delete the selected board");
  await page.keyboard.press("Escape");
  await expect(help).toBeHidden();

  // Create: Esc cancels, an empty title is refused, then a real one.
  await page.keyboard.press("a");
  const create = page.getByRole("dialog", { name: "New board title" });
  await expect(create.getByRole("textbox")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(create).toBeHidden();

  await page.keyboard.press("a");
  await page.keyboard.press("Enter");
  await expect(create.getByRole("alert")).toHaveText("Title can't be empty");
  await page.keyboard.type(title);
  await page.keyboard.press("Enter");
  await expect(create).toBeHidden();
  await expect(tile(page, title)).toHaveAttribute("aria-selected", "true");
  await expect(tile(page, title)).toContainText("0 cards · 0 done");
  await expect(tile(page, title)).toContainText("Todo 0 · Doing 0 · Done 0");

  // Enter opens the board (stub until M3a); Esc goes back with the same selection.
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/b\/[0-9a-f-]{36}$/);
  await expect(page.getByTestId("mode")).toHaveText("-- BOARD --");
  await expect(page.getByTestId("board-title")).toContainText(title);
  await page.keyboard.press("?");
  await expect(page.getByRole("dialog", { name: "Help" })).toContainText("back to the dashboard");
  await page.keyboard.press("Control+c");
  await expect(page.getByRole("dialog", { name: "Help" })).toBeHidden();
  await expect(page.getByTestId("mode")).toHaveText("-- BOARD --"); // one level only
  await page.keyboard.press("Escape");
  await expect(page).toHaveURL(/\/$/);
  await expect(tile(page, title)).toHaveAttribute("aria-selected", "true");

  // Rename: the prompt starts with the old title selected, so typing replaces it.
  await page.keyboard.press("r");
  const rename = page.getByRole("dialog", { name: "Rename board" });
  await expect(rename.getByRole("textbox")).toHaveValue(title);
  await page.keyboard.type(renamed);
  await page.keyboard.press("Enter");
  await expect(rename).toBeHidden();
  await expect(tile(page, renamed)).toHaveAttribute("aria-selected", "true");
  await expect(tile(page, title)).toHaveCount(0);

  // Delete: n keeps it, then y deletes it.
  await page.keyboard.press("d");
  const confirm = page.getByRole("alertdialog");
  await expect(confirm).toContainText(`Delete board "${renamed}"`);
  await page.keyboard.press("n");
  await expect(confirm).toBeHidden();
  await expect(tile(page, renamed)).toHaveCount(1);
  await page.keyboard.press("d");
  await page.keyboard.press("y");
  await expect(tile(page, renamed)).toHaveCount(0);
  await page.reload();
  await expect(page.getByTestId("mode")).toHaveText("-- DASHBOARD --");
  await expect(tile(page, renamed)).toHaveCount(0);

  // Fast deletes: the second `d` acts on the neighbour, not on the board being deleted.
  // Both boards are new and last in the grid, so nothing else can be selected here.
  for (const t of [`${title} one`, `${title} two`]) {
    await page.keyboard.press("a");
    await page.keyboard.type(t);
    await page.keyboard.press("Enter");
    await expect(tile(page, t)).toHaveAttribute("aria-selected", "true");
  }
  await page.keyboard.press("d");
  await page.keyboard.press("y");
  await page.keyboard.press("d");
  await page.keyboard.press("y");
  await expect(tile(page, title)).toHaveCount(0);
  await page.reload();
  await expect(page.getByTestId("mode")).toHaveText("-- DASHBOARD --");
  await expect(tile(page, title)).toHaveCount(0);

  // Log out: Ctrl+C cancels, y confirms.
  await page.keyboard.press("Q");
  await expect(page.getByRole("alertdialog")).toContainText("Log out?");
  await page.keyboard.press("Control+c");
  await expect(page.getByRole("alertdialog")).toBeHidden();
  await page.keyboard.press("Q");
  await page.keyboard.press("y");
  await expect(page).toHaveURL(/\/login$/);
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
});
