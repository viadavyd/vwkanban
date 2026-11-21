import { expect, test, type Page } from "@playwright/test";
import { card, column, expectSelected, expectTitles, settled, STATE } from "./helpers";

// Keyboard only (no clicks, no fill()): every M3a board key on a fresh board.
test.use({ storageState: STATE });

const boardTitle = `M3a e2e ${Date.now()}`;

async function newCard(page: Page, key: "a" | "A", title: string) {
  await page.keyboard.press(key);
  await expect(page.getByLabel("New card title")).toBeFocused();
  await page.keyboard.type(title);
  await page.keyboard.press("Enter");
  await expect(page.getByLabel("New card title")).toHaveCount(0);
  await expectSelected(page, title);
}

test("keyboard-only board: a A j k h l Space d ? Esc", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("mode")).toHaveText("-- DASHBOARD --");

  // A fresh board, opened with Enter.
  await page.keyboard.press("a");
  await page.keyboard.type(boardTitle);
  await page.keyboard.press("Enter");
  await expect(page.getByRole("option").filter({ hasText: boardTitle })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/b\/[0-9a-f-]{36}$/);
  await expect(page.getByTestId("mode")).toHaveText("-- BOARD --");
  await expect(page.getByTestId("board-title")).toContainText(boardTitle);
  await expect(page.getByTestId("column")).toHaveCount(3);

  // The placeholder: Esc, Ctrl+C and an empty Enter each discard it, one level only.
  for (const key of ["Escape", "Control+c", "Enter"]) {
    await page.keyboard.press("a");
    await expect(page.getByLabel("New card title")).toBeFocused();
    await page.keyboard.press(key);
    await expect(page.getByLabel("New card title")).toHaveCount(0);
    await expect(page.getByTestId("mode")).toHaveText("-- BOARD --");
  }
  await expect(page.locator("[data-card]")).toHaveCount(0);

  // a = below the selection, A = above it.
  await newCard(page, "a", "one");
  await newCard(page, "a", "three");
  await page.keyboard.press("k");
  await expectSelected(page, "one");
  await newCard(page, "a", "two");
  await page.keyboard.press("k");
  await newCard(page, "A", "first");
  await expectTitles(page, "Todo", ["first", "one", "two", "three"]);
  await expect(column(page, "Todo").getByTestId("column-count")).toHaveText("4");

  // j / k within the column, stopping at the ends.
  await page.keyboard.press("k");
  await expectSelected(page, "first");
  await page.keyboard.press("j");
  await page.keyboard.press("j");
  await expectSelected(page, "two");
  await page.keyboard.press("j");
  await page.keyboard.press("j");
  await expectSelected(page, "three");
  await page.keyboard.press("k");
  await page.keyboard.press("k");
  await expectSelected(page, "one");

  // h / l across columns, empty ones included; the row is kept.
  await page.keyboard.press("l");
  await expect(page.locator('[data-card][aria-selected="true"]')).toHaveCount(0);
  await expect(column(page, "Doing")).toHaveClass(/current/);
  await page.keyboard.press("l");
  await expect(column(page, "Done")).toHaveClass(/current/);
  await page.keyboard.press("l"); // last column: stays
  await expect(column(page, "Done")).toHaveClass(/current/);
  await page.keyboard.press("h");
  await page.keyboard.press("h");
  await expectSelected(page, "one");
  await page.keyboard.press("h"); // first column: stays
  await expectSelected(page, "one");

  // Numbers come from the server, in creation order.
  await expect(card(page, "first").getByTestId("card-meta")).toHaveText("#4");
  await expect(card(page, "three").getByTestId("card-meta")).toHaveText("#2");

  // Space toggles done; it survives a reload.
  await page.keyboard.press("Space");
  const done = card(page, "one").getByRole("checkbox");
  await expect(done).toHaveAttribute("aria-checked", "true");
  await settled(page);
  await page.reload();
  await settled(page);
  await expect(card(page, "one").getByRole("checkbox")).toHaveAttribute("aria-checked", "true");
  await expectSelected(page, "first"); // a fresh load selects the first card

  // Space again: back to not done.
  await page.keyboard.press("j");
  await page.keyboard.press("Space");
  await expect(card(page, "one").getByRole("checkbox")).toHaveAttribute("aria-checked", "false");
  await settled(page);
  await page.keyboard.press("Space");
  await expect(card(page, "one").getByRole("checkbox")).toHaveAttribute("aria-checked", "true");

  // d deletes; the selection moves to the next card, else the previous one.
  await page.keyboard.press("k");
  await page.keyboard.press("d");
  await expect(card(page, "first")).toHaveCount(0);
  await expectSelected(page, "one");
  await settled(page);
  await page.keyboard.press("j");
  await page.keyboard.press("j");
  await page.keyboard.press("d");
  await expectSelected(page, "two");
  await settled(page);
  await page.reload();
  await settled(page);
  await expectTitles(page, "Todo", ["one", "two"]);

  // Help lists the board keys; Esc closes only the help.
  await page.keyboard.press("?");
  const help = page.getByRole("dialog", { name: "Help" });
  await expect(help).toContainText("new card below the selection");
  await expect(help).toContainText("toggle done");
  await expect(help).toContainText("next column");
  await page.keyboard.press("Escape");
  await expect(help).toBeHidden();
  await expect(page.getByTestId("mode")).toHaveText("-- BOARD --");

  // Esc → dashboard, with the tile counts updated.
  await page.keyboard.press("Escape");
  await expect(page).toHaveURL(/\/$/);
  const tile = page.getByRole("option").filter({ hasText: boardTitle });
  await expect(tile).toHaveAttribute("aria-selected", "true");
  await expect(tile).toContainText("2 cards · 1 done");
  await expect(tile).toContainText("Todo 2 · Doing 0 · Done 0");

  // Ctrl+C on the board goes back too.
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("mode")).toHaveText("-- BOARD --");
  await page.keyboard.press("Control+c");
  await expect(page).toHaveURL(/\/$/);
  await expect(tile).toHaveAttribute("aria-selected", "true"); // dashboard loaded

  // Clean up.
  const gone = page.waitForResponse((r) => r.request().method() === "DELETE");
  await page.keyboard.press("d");
  await page.keyboard.press("y");
  expect((await gone).status()).toBe(204);
});
