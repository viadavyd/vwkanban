import { expect, test, type Browser, type Page } from "@playwright/test";
import {
  ADMIN,
  BOB,
  BOB_STATE,
  card,
  expectSelected,
  expectTitles,
  settled,
  STATE,
} from "./helpers";

// M4: two browser contexts (the admin and a second user) on one board, through the real
// stack (nginx proxies the WebSocket). Keyboard only. Every wait is a web-first assertion
// on what the other page shows; nothing sleeps.

const presence = (page: Page) => page.getByTestId("presence").getByRole("listitem");
const message = (page: Page) => page.locator("main .message");

async function newCard(page: Page, title: string) {
  await page.keyboard.press("a");
  await expect(page.getByLabel("New card title")).toBeFocused();
  await page.keyboard.type(title);
  await page.keyboard.press("Enter");
  await expect(page.getByLabel("New card title")).toHaveCount(0);
  await expectSelected(page, title);
}

/** The admin creates a board from the dashboard, opens it and shares it with BOB through
 * the members overlay (M, a). Returns the board's id. */
async function sharedBoard(page: Page, title: string): Promise<string> {
  await page.goto("/");
  await expect(page.getByTestId("mode")).toHaveText("-- DASHBOARD --");
  await page.keyboard.press("a");
  await page.keyboard.type(title);
  await page.keyboard.press("Enter");
  await expect(page.getByRole("option").filter({ hasText: title })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/b\/[0-9a-f-]{36}$/);
  await settled(page);

  await page.keyboard.press("M");
  const members = page.getByRole("dialog", { name: "Members" });
  await expect(members.locator(`[data-member="${ADMIN}"]`)).toContainText("owner · you");
  await page.keyboard.press("a");
  await expect(page.getByRole("textbox", { name: "Add member (username)" })).toBeFocused();
  await page.keyboard.type(BOB);
  await page.keyboard.press("Enter");
  await expect(members.locator(`[data-member="${BOB}"]`)).toContainText("editor");
  await expect(members.getByRole("status")).toHaveText(`${BOB} can now edit this board`);
  await page.keyboard.press("Escape");
  await expect(members).toHaveCount(0);
  await expect(page.getByTestId("mode")).toHaveText("-- BOARD --"); // one level only
  return page.url().split("/b/")[1];
}

async function twoUsers(browser: Browser) {
  const a = await browser.newContext({ storageState: STATE });
  const b = await browser.newContext({ storageState: BOB_STATE });
  return {
    pa: await a.newPage(),
    pb: await b.newPage(),
    close: () => a.close().then(() => b.close()),
  };
}

test("two users see each other's changes live", async ({ browser }) => {
  const { pa, pb, close } = await twoUsers(browser);
  try {
    const boardId = await sharedBoard(pa, `M4 live ${Date.now()}`);
    await newCard(pa, "alpha");
    await newCard(pa, "beta");
    await settled(pa);

    await pb.goto(`/b/${boardId}`);
    await settled(pb);
    await expectTitles(pb, "Todo", ["alpha", "beta"]);

    // Presence: each sees the other's initial; the dot says live.
    await expect(presence(pa)).toHaveCount(1);
    await expect(presence(pa).first()).toHaveAttribute("aria-label", BOB);
    await expect(presence(pb).first()).toHaveAttribute("aria-label", ADMIN);
    await expect(pb.getByTestId("sync")).toContainText("● live");

    // A moves alpha to Doing (k x l p): B sees it.
    await pa.keyboard.press("k");
    await expectSelected(pa, "alpha");
    await pa.keyboard.press("x");
    await pa.keyboard.press("l");
    await pa.keyboard.press("p");
    await settled(pa);
    await expectTitles(pb, "Doing", ["alpha"]);
    await expectTitles(pb, "Todo", ["beta"]);

    // B moves beta under alpha (x l p): A sees it.
    await expectSelected(pb, "beta");
    await pb.keyboard.press("x");
    await pb.keyboard.press("l");
    await pb.keyboard.press("p");
    await settled(pb);
    await expectTitles(pa, "Doing", ["alpha", "beta"]);
    await expectTitles(pa, "Todo", []);

    // B toggles beta done: A sees it.
    await expectSelected(pb, "beta");
    await pb.keyboard.press("Space");
    await expect(card(pa, "beta").getByRole("checkbox")).toHaveAttribute("aria-checked", "true");

    // A creates a card: B sees it with its server number.
    await pa.keyboard.press("h");
    await newCard(pa, "gamma");
    await expectTitles(pb, "Todo", ["gamma"]);
    await expect(card(pb, "gamma").getByTestId("card-meta")).toHaveText("#3");

    // B leaves the board: A's presence empties.
    await pb.keyboard.press("Escape");
    await expect(pb.getByTestId("mode")).toHaveText("-- DASHBOARD --");
    await expect(presence(pa)).toHaveCount(0);
  } finally {
    await close();
  }
});

test("a removed member is disconnected and sent back to the dashboard", async ({ browser }) => {
  const { pa, pb, close } = await twoUsers(browser);
  try {
    const boardId = await sharedBoard(pa, `M4 remove ${Date.now()}`);
    await pb.goto(`/b/${boardId}`);
    await settled(pb);
    await expect(presence(pa)).toHaveCount(1);

    // The owner removes BOB (M, j, d, y): BOB's page goes back to the dashboard and says why.
    await pa.keyboard.press("M");
    const members = pa.getByRole("dialog", { name: "Members" });
    await expect(members.getByRole("option")).toHaveCount(2);
    await pa.keyboard.press("j");
    await expect(members.locator(`[data-member="${BOB}"]`)).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await pa.keyboard.press("d");
    await expect(pa.getByRole("alertdialog")).toContainText(`Remove ${BOB} from this board?`);
    await pa.keyboard.press("y");
    await expect(members.getByRole("status")).toHaveText(`${BOB} was removed`);
    await expect(members.getByRole("option")).toHaveCount(1);

    await expect(pb.getByTestId("mode")).toHaveText("-- DASHBOARD --");
    await expect(message(pb)).toHaveText("you are no longer a member of that board");
    await expect(presence(pa)).toHaveCount(0);

    // The board is gone from BOB's dashboard, and its URL no longer opens it.
    await pb.goto(`/b/${boardId}`);
    await expect(pb.getByTestId("mode")).toHaveText("-- DASHBOARD --");
    await expect(message(pb)).toHaveText("that board doesn't exist or isn't shared with you");
  } finally {
    await close();
  }
});
