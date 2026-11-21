import { readFile } from "node:fs/promises";
import { expect, test, type Page } from "@playwright/test";
import { ADMIN, BOB, BOB_STATE, expectTitles, seedBoard, settled, STATE } from "./helpers";

// M6: CSV export (E) and import (I: file picker, preview, y) through the real stack
// (nginx in front). Keyboard only; the test sets the file on the hidden input after `I`.
// Every wait is a web-first assertion or settled(); nothing sleeps.

test.use({ storageState: STATE });

const CRLF = "\r\n";
/** A file in exactly the form the app exports (so import → export gives it back): a
 * child, a new column, unicode, quotes and newlines, formula-like cells escaped. */
const FIXTURE =
  [
    "id,title,status,date,parent,is_done,tags,description",
    '1,Plan the hackathon,Todo,2026-12-01,,false,ünïcode;日本語,"Line one, with ""quotes""\nline two"',
    "2,Book a room,,,1,true,,",
    "3,'=SUM(A1:A2),Todo,,,false,'-minus,",
    "4,Waiting on keys,Blocked,,,false,,",
  ].join(CRLF) + CRLF;

const message = (page: Page) => page.locator("main .message");
const confirm = (page: Page) => page.getByRole("alertdialog");
const columnNames = (page: Page) => page.getByTestId("column").locator("header .name");

async function openBoard(page: Page, id: string) {
  await page.goto(`/b/${id}`);
  await settled(page);
}

/** `E`: returns the downloaded file's bytes. */
async function exportBytes(page: Page): Promise<Buffer> {
  const download = page.waitForEvent("download");
  await page.keyboard.press("E");
  const file = await download;
  expect(file.suggestedFilename()).toMatch(/\.csv$/);
  return readFile(await file.path());
}

/** `I`, then this file on the hidden input. `I` clears the input and opens the picker
 * synchronously in its keydown, so the file set after the press is the one `change`
 * reads. (Waiting for the "filechooser" event instead timed out in ~1 of 10 runs.) */
async function pickFile(page: Page, body: string | Buffer, name = "cards.csv") {
  await page.keyboard.press("I");
  await page
    .getByTestId("csv-file")
    .setInputFiles({ name, mimeType: "text/csv", buffer: Buffer.from(body) });
}

test("import a file, then export it back byte for byte", async ({ page, request }) => {
  const board = await seedBoard(request, `M6 import ${Date.now()}`);
  await openBoard(page, board.id);

  await pickFile(page, FIXTURE);
  await expect(confirm(page)).toContainText("Import 4 cards into");
  await expect(confirm(page)).toContainText("keeping their numbers");
  await expect(page.getByTestId("confirm-details")).toHaveText("new columns: Blocked");
  await page.keyboard.press("y");
  await expect(confirm(page)).toHaveCount(0);
  await expect(message(page)).toHaveText("imported 4 cards");
  await settled(page);

  await expect(columnNames(page)).toHaveText(["Todo", "Doing", "Done", "Blocked"]);
  await expectTitles(page, "Todo", ["Plan the hackathon", "=SUM(A1:A2)"]);
  await expectTitles(page, "Blocked", ["Waiting on keys"]);
  await expect(page.locator('[data-card][data-number="1"]')).toContainText("1/1");

  expect((await exportBytes(page)).toString("utf-8")).toBe(FIXTURE);
});

test("export → import into an empty board → export is identical", async ({ page, request }) => {
  const a = await seedBoard(request, `M6 source ${Date.now()}`, [
    "first, with a comma",
    '"quoted" title',
    "@mention",
  ]);
  await openBoard(page, a.id);
  const first = await exportBytes(page);
  expect(first.toString("utf-8")).toContain("'@mention");

  const b = await seedBoard(request, `M6 copy ${Date.now()}`);
  await openBoard(page, b.id);
  await pickFile(page, first);
  await expect(confirm(page)).toContainText("Import 3 cards");
  await page.keyboard.press("y");
  await expect(message(page)).toHaveText("imported 3 cards");
  await settled(page);
  await expectTitles(page, "Todo", ["first, with a comma", '"quoted" title', "@mention"]);
  expect(await exportBytes(page)).toEqual(first);
});

test("n cancels the preview and a bad file is refused with its rows", async ({ page, request }) => {
  const board = await seedBoard(request, `M6 refused ${Date.now()}`, ["kept"]);
  await openBoard(page, board.id);

  await pickFile(page, FIXTURE);
  await expect(confirm(page)).toContainText("with new numbers"); // the board has a card
  await page.keyboard.press("n");
  await expect(confirm(page)).toHaveCount(0);
  await expectTitles(page, "Todo", ["kept"]);

  const bad = ["title,date", "ok,", "bad date,2026-02-30", "also ok,2026-01-01"].join(CRLF);
  await pickFile(page, bad);
  await expect(message(page)).toContainText("nothing imported, 1 bad rows: row 3: date");
  await expect(confirm(page)).toHaveCount(0);
  await settled(page);
  await expectTitles(page, "Todo", ["kept"]);

  // Keys still reach the board after the picker (the hidden input never holds focus).
  await page.keyboard.press("?");
  await expect(page.getByRole("dialog", { name: /help/i })).toContainText(
    "import cards from a CSV file",
  );
  await page.keyboard.press("Escape");
});

test("a teammate's board reloads after an import", async ({ browser, request }) => {
  const board = await seedBoard(request, `M6 shared ${Date.now()}`, ["before"], BOB);
  const a = await browser.newContext({ storageState: STATE });
  const b = await browser.newContext({ storageState: BOB_STATE });
  try {
    const pa = await a.newPage();
    const pb = await b.newPage();
    await openBoard(pa, board.id);
    await openBoard(pb, board.id);
    await expectTitles(pb, "Todo", ["before"]);

    await pickFile(pa, FIXTURE);
    await expect(confirm(pa)).toContainText("Import 4 cards");
    await pa.keyboard.press("y");
    await expect(message(pa)).toHaveText("imported 4 cards");
    await settled(pa);

    // Bob's tab got the board.import event and reloaded the board over the live socket.
    await expect(message(pb)).toHaveText(`${ADMIN} imported 4 cards`);
    await expect(columnNames(pb)).toHaveText(["Todo", "Doing", "Done", "Blocked"]);
    await expectTitles(pb, "Todo", ["before", "Plan the hackathon", "=SUM(A1:A2)"]);
    await expectTitles(pb, "Blocked", ["Waiting on keys"]);
    await settled(pb);

    // And it stays live: bob's next op reaches the admin.
    await pb.keyboard.press("l");
    await pb.keyboard.press("l");
    await pb.keyboard.press("l");
    await pb.keyboard.press("Space");
    await settled(pb);
    await expect(
      pa.locator('[data-card][data-number="5"]').getByRole("checkbox", { name: "done" }),
    ).toHaveAttribute("aria-checked", "true");
  } finally {
    await a.close();
    await b.close();
  }
});
