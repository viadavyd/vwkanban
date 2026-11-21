import { expect, test, type Page } from "@playwright/test";
import { card, column, expectSelected, expectTitles, ORIGIN, settled, STATE } from "./helpers";

// Keyboard only (no clicks, no fill()): every M3b board key — y p x u, s a/r/c/d, H L —
// on a fresh board. The one exception is the seed: cards with children can't be made from
// the keyboard before card mode (M5), so one is created through the ops API.
test.use({ storageState: STATE });

const boardTitle = `M3b e2e ${Date.now()}`;

const byNumber = (page: Page, n: number) => page.locator(`[data-card][data-number="${n}"]`);
const columnNames = (page: Page) => page.getByTestId("column").locator("header .name");
const message = (page: Page) => page.locator("main .message");

async function newCard(page: Page, title: string) {
  await page.keyboard.press("a");
  await expect(page.getByLabel("New card title")).toBeFocused();
  await page.keyboard.type(title);
  await page.keyboard.press("Enter");
  await expect(page.getByLabel("New card title")).toHaveCount(0);
  await expectSelected(page, title);
}

/** Presses a key that sends an op and waits until the server has answered it (an ack or a
 * reject: what it shows is checked after). */
async function press(page: Page, key: string) {
  await page.keyboard.press(key);
  await settled(page);
}

test("keyboard-only register, move, undo and columns", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("mode")).toHaveText("-- DASHBOARD --");
  await page.keyboard.press("a");
  await page.keyboard.type(boardTitle);
  await page.keyboard.press("Enter");
  await expect(page.getByRole("option").filter({ hasText: boardTitle })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/b\/[0-9a-f-]{36}$/);
  await expect(page.getByTestId("column")).toHaveCount(3);
  const boardId = page.url().split("/b/")[1];

  // Seed: #1 "parent" with two children (#2 done, #3), through the ops API.
  const detail = await (await page.request.get(`/api/boards/${boardId}`)).json();
  const todo = detail.statuses[0].id;
  const uuid = () => crypto.randomUUID(); // the server takes any UUID; the app uses v7
  const seeded = await page.request.post(`/api/boards/${boardId}/ops`, {
    headers: { Origin: ORIGIN },
    data: {
      client_id: uuid(),
      op: {
        op_id: uuid(),
        kind: "card.create",
        base_seq: 0,
        data: {
          id: uuid(),
          status_id: todo,
          title: "parent",
          children: [
            { id: uuid(), title: "kid one", is_done: true },
            { id: uuid(), title: "kid two" },
          ],
        },
      },
    },
  });
  expect(seeded.status(), await seeded.text()).toBe(200);
  await page.reload();
  await settled(page);
  await expectTitles(page, "Todo", ["parent"]);
  await expectSelected(page, "parent");
  await expect(byNumber(page, 1).getByTestId("card-meta")).toHaveText("#1 · ☐ 1/2");

  // y p: a copy with its children (new numbers) below the selection; u takes it back.
  await page.keyboard.press("y");
  await press(page, "p");
  await expectTitles(page, "Todo", ["parent", "parent"]);
  await expect(byNumber(page, 4)).toHaveAttribute("aria-selected", "true");
  await expect(byNumber(page, 4).getByTestId("card-meta")).toHaveText("#4 · ☐ 1/2");
  await press(page, "u");
  await expectTitles(page, "Todo", ["parent"]);

  await newCard(page, "a");
  await newCard(page, "b");
  await expectTitles(page, "Todo", ["parent", "a", "b"]);

  // x marks (dimmed, shown in the top bar); Esc clears only the mark.
  await page.keyboard.press("x");
  await expect(page.getByTestId("pending")).toHaveText(/^x: #\d+$/);
  await expect(card(page, "b")).toHaveClass(/marked/);
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("pending")).toHaveCount(0);
  await expect(card(page, "b")).not.toHaveClass(/marked/);
  await expect(page).toHaveURL(/\/b\//); // still on the board

  // x … l p moves the marked card; the register is consumed.
  await page.keyboard.press("x");
  await page.keyboard.press("l");
  await press(page, "p");
  await expectTitles(page, "Doing", ["b"]);
  await expectTitles(page, "Todo", ["parent", "a"]);
  await expect(page.getByTestId("pending")).toHaveCount(0);
  await expectSelected(page, "b");

  // The children follow their parent; u moves it back.
  await page.keyboard.press("h");
  await page.keyboard.press("k");
  await expectSelected(page, "parent");
  await page.keyboard.press("x");
  await page.keyboard.press("l");
  await press(page, "p");
  await expectTitles(page, "Doing", ["b", "parent"]);
  await expect(byNumber(page, 1).getByTestId("card-meta")).toHaveText("#1 · ☐ 1/2");
  await press(page, "u");
  await expectTitles(page, "Todo", ["parent", "a"]);
  await expectTitles(page, "Doing", ["b"]);
  await expectSelected(page, "parent");

  // u undoes a toggle.
  await page.keyboard.press("j");
  await expectSelected(page, "a");
  const check = card(page, "a").getByRole("checkbox");
  await press(page, "Space");
  await expect(check).toHaveAttribute("aria-checked", "true");
  await press(page, "u");
  await expect(check).toHaveAttribute("aria-checked", "false");

  // u undoes a delete (restore).
  await press(page, "d");
  await expectTitles(page, "Todo", ["parent"]);
  await press(page, "u");
  await expectTitles(page, "Todo", ["parent", "a"]);

  // d puts the deleted card in the register: p pastes it back as a copy.
  await page.keyboard.press("j");
  await expectSelected(page, "a");
  const numberOfA = Number(await card(page, "a").getAttribute("data-number"));
  await press(page, "d");
  await expectSelected(page, "parent");
  await press(page, "p");
  await expectTitles(page, "Todo", ["parent", "a"]);
  await expect(card(page, "a")).not.toHaveAttribute("data-number", String(numberOfA));
  await expect(card(page, "a")).not.toHaveAttribute("data-number", "0"); // confirmed

  // Nothing left of the above is pending: a reload shows the same board.
  await page.reload();
  await settled(page);
  await expectTitles(page, "Todo", ["parent", "a"]);
  await expectTitles(page, "Doing", ["b"]);
  await expect(byNumber(page, 1).getByTestId("card-meta")).toHaveText("#1 · ☐ 1/2");
  await expect(card(page, "a").getByRole("checkbox")).toHaveAttribute("aria-checked", "false");
  await expectSelected(page, "parent");

  // s is a prefix: the top bar shows it, Esc cancels only it.
  await page.keyboard.press("s");
  await expect(page.getByTestId("pending")).toHaveText("s…");
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("pending")).toHaveCount(0);
  await expect(page).toHaveURL(/\/b\//);

  // s a: a new column to the right of the current one; names are unique.
  await page.keyboard.press("s");
  await page.keyboard.press("a");
  const prompt = page.getByRole("dialog", { name: "New column name" });
  await expect(prompt.getByRole("textbox")).toBeFocused();
  await page.keyboard.type("todo");
  await page.keyboard.press("Enter");
  await expect(prompt.getByRole("alert")).toHaveText('a column named "Todo" already exists');
  await page.keyboard.press("Control+a");
  await page.keyboard.type("Review");
  await press(page, "Enter");
  await expect(prompt).toHaveCount(0);
  await expect(columnNames(page)).toHaveText(["Todo", "Review", "Doing", "Done"]);
  await expect(column(page, "Review")).toHaveClass(/current/);

  // s r renames, s c cycles the colour (green → purple: the 4th column got green).
  await page.keyboard.press("s");
  await page.keyboard.press("r");
  const rename = page.getByRole("dialog", { name: "Rename column" });
  await expect(rename.getByRole("textbox")).toHaveValue("Review");
  await page.keyboard.type("QA");
  await press(page, "Enter");
  await expect(columnNames(page)).toHaveText(["Todo", "QA", "Doing", "Done"]);
  const header = column(page, "QA").locator("header");
  await expect(header).toHaveCSS("border-top-color", "rgb(23, 128, 109)");
  await page.keyboard.press("s");
  await press(page, "c");
  await expect(header).toHaveCSS("border-top-color", "rgb(94, 43, 151)");

  // H / L move the column; they stop at the edges; u undoes a column move.
  await press(page, "H");
  await expect(columnNames(page)).toHaveText(["QA", "Todo", "Doing", "Done"]);
  await page.keyboard.press("H"); // already first: nothing is sent
  await press(page, "L");
  await press(page, "L");
  await expect(columnNames(page)).toHaveText(["Todo", "Doing", "QA", "Done"]);
  await expect(column(page, "QA")).toHaveClass(/current/);
  await press(page, "u");
  await expect(columnNames(page)).toHaveText(["Todo", "QA", "Doing", "Done"]);

  await page.reload();
  await settled(page);
  await expect(columnNames(page)).toHaveText(["Todo", "QA", "Doing", "Done"]);
  await expect(column(page, "QA").locator("header")).toHaveCSS(
    "border-top-color",
    "rgb(94, 43, 151)",
  );

  // s d is refused on a column with cards (the server refuses it too).
  await expect(column(page, "Todo")).toHaveClass(/current/);
  await page.keyboard.press("s");
  await page.keyboard.press("d");
  await expect(message(page)).toHaveText('column "Todo" is not empty');
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  await expect(columnNames(page)).toHaveText(["Todo", "QA", "Doing", "Done"]);
  const refused = await page.request.post(`/api/boards/${boardId}/ops`, {
    headers: { Origin: ORIGIN },
    data: {
      client_id: uuid(),
      op: { op_id: uuid(), kind: "status.delete", base_seq: 0, data: { id: todo } },
    },
  });
  expect(refused.status()).toBe(422);

  // A column whose only card is soft-deleted can be deleted; that card is purged, so after
  // u brings the column back, undoing the card's delete is `gone`.
  await page.keyboard.press("l");
  await expect(column(page, "QA")).toHaveClass(/current/);
  await newCard(page, "temp");
  await press(page, "d");
  await expect(column(page, "QA").locator("[data-card]")).toHaveCount(0);
  await page.keyboard.press("s");
  await page.keyboard.press("d");
  await expect(page.getByRole("alertdialog")).toContainText('Delete column "QA"?');
  await press(page, "y");
  await expect(columnNames(page)).toHaveText(["Todo", "Doing", "Done"]);
  await press(page, "u");
  await expect(columnNames(page)).toHaveText(["Todo", "QA", "Doing", "Done"]);
  await press(page, "u");
  await expect(message(page)).toContainText("gone for good");
  await expect(column(page, "QA").locator("[data-card]")).toHaveCount(0);

  // Help lists the new keys, the column commands with their prefix.
  await page.keyboard.press("?");
  const help = page.getByRole("dialog", { name: "Help" });
  await expect(help).toContainText("copy the card (with its children)");
  await expect(help).toContainText("undo your last change");
  await expect(help).toContainText("Columns (after s)");
  await expect(help.locator("kbd", { hasText: /^s a$/ })).toHaveCount(1);
  await page.keyboard.press("Escape");
  await expect(help).toBeHidden();

  // Clean up.
  await page.keyboard.press("Escape");
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("option").filter({ hasText: boardTitle })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  const gone = page.waitForResponse((r) => r.request().method() === "DELETE");
  await page.keyboard.press("d");
  await page.keyboard.press("y");
  expect((await gone).status()).toBe(204);
});
