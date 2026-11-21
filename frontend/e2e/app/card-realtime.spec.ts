import { expect, test, type Browser, type Page } from "@playwright/test";
import {
  ADMIN,
  BOB,
  BOB_STATE,
  card,
  cardView,
  field,
  mode,
  row,
  seedBoard,
  serverCard,
  settled,
  STATE,
} from "./helpers";

// M5, two browser contexts (the admin "A" and a second user "B") editing one card through
// the real stack (nginx proxies the WebSocket). Keyboard only, except the seed. Waits
// are web-first assertions on what a page shows, and settled(page); nothing sleeps.

async function twoUsers(browser: Browser) {
  const a = await browser.newContext({ storageState: STATE });
  const b = await browser.newContext({ storageState: BOB_STATE });
  return {
    pa: await a.newPage(),
    pb: await b.newPage(),
    close: () => a.close().then(() => b.close()),
  };
}

async function open(page: Page, title: string) {
  await expect(card(page, title)).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("i");
  await expect(mode(page)).toHaveText("-- CARD --");
}

/** To the description (k to the top, then j) and start typing at its end. */
async function editDescription(page: Page) {
  for (let i = 0; i < 3; i++) await page.keyboard.press("k");
  await expect(row(page, "title")).toHaveAttribute("aria-current", "true");
  for (let i = 0; i < 3; i++) await page.keyboard.press("j");
  await expect(row(page, "description")).toHaveAttribute("aria-current", "true");
  await page.keyboard.press("a");
  await expect(field(page)).toHaveAttribute("data-ready", "true");
  await expect(mode(page)).toHaveText("-- INSERT --");
}

/** INSERT → NORMAL → leave the field (saves). */
async function leave(page: Page) {
  await page.keyboard.press("Escape");
  await expect(mode(page)).toHaveText("-- NORMAL --");
  await page.keyboard.press("Escape");
  await expect(mode(page)).toHaveText("-- CARD --");
}

async function ex(page: Page, command: string) {
  await page.keyboard.type(`:${command}`);
  await page.keyboard.press("Enter");
}

const editorText = (page: Page) => field(page).locator(".cm-content");

test("both edit one description: conflict prompt, neither text lost, :w! and :e!", async ({
  browser,
}) => {
  const { pa, pb, close } = await twoUsers(browser);
  const board = await seedBoard(pa.request, `M5 conflict ${Date.now()}`, ["shared"], BOB);
  const id = board.cards[0].id;
  for (const p of [pa, pb]) {
    await p.goto(`/b/${board.id}`);
    await settled(p);
    await open(p, "shared");
    await editDescription(p);
  }
  await pa.keyboard.type("A's text");
  await pb.keyboard.type("B's text");

  // A saves first. B, still typing, is told; its editor is untouched.
  await leave(pa);
  await settled(pa);
  await expect(pb.getByTestId("choice")).toContainText(":w! keep mine · :e! take theirs");
  await expect(editorText(pb)).toHaveText("B's text");

  // B saves anyway: refused (frozen base_seq), the draft stays on the row.
  await leave(pb);
  await settled(pb);
  await expect(row(pb, "description").getByTestId("choice")).toContainText(
    `description was changed by ${ADMIN}`,
  );
  await expect(row(pb, "description")).toContainText("B's text");
  // Neither text is lost: A's is on the server and on A's screen, B's is B's draft.
  expect((await serverCard(pa.request, board.id, id)).description).toBe("A's text");
  await expect(row(pa, "description")).toHaveText("A's text");

  // B reopens the draft and keeps it with :w!.
  await pb.keyboard.press("i");
  await expect(field(pb)).toHaveAttribute("data-ready", "true");
  await expect(editorText(pb)).toHaveText("B's text");
  await ex(pb, "w!");
  await settled(pb);
  await expect(row(pa, "description")).toHaveText("B's text");
  expect((await serverCard(pa.request, board.id, id)).description).toBe("B's text");

  // A edits again while B is still in the field: B takes theirs with :e!.
  await editDescription(pa);
  await pa.keyboard.type(" and A");
  await leave(pa);
  await settled(pa);
  await expect(pb.getByTestId("choice")).toContainText("remote changed");
  await ex(pb, "e!");
  await expect(editorText(pb)).toHaveText("B's text and A");
  await pb.keyboard.press("Escape"); // NORMAL: leave, nothing to save
  await expect(mode(pb)).toHaveText("-- CARD --");
  await settled(pb);
  await expect(row(pb, "description")).toHaveText("B's text and A");
  await expect(row(pb, "description").getByTestId("choice")).toHaveCount(0);
  expect((await serverCard(pa.request, board.id, id)).description).toBe("B's text and A");
  await close();
});

test("children sync to the second client", async ({ browser }) => {
  const { pa, pb, close } = await twoUsers(browser);
  const board = await seedBoard(pa.request, `M5 kids ${Date.now()}`, ["parent"], BOB);
  for (const p of [pa, pb]) {
    await p.goto(`/b/${board.id}`);
    await settled(p);
  }
  await open(pa, "parent");
  await open(pb, "parent");
  await pa.keyboard.press("o"); // from the title row: a child at the top
  await pa.keyboard.type("from A");
  await pa.keyboard.press("Enter");
  await settled(pa);
  await expect(cardView(pb).getByTestId("child-title")).toHaveText(["from A"]);
  await pa.keyboard.press("Space");
  await settled(pa);
  await expect(cardView(pb).locator('[data-row^="child:"]')).toContainText("☑");
  await pb.keyboard.press("Escape");
  await expect(card(pb, "parent").getByTestId("card-meta")).toHaveText(/☐ 1\/1/);
  await close();
});

test("a card deleted while A edits it: banner, and the draft comes back with p", async ({
  browser,
}) => {
  const { pa, pb, close } = await twoUsers(browser);
  const board = await seedBoard(pa.request, `M5 deleted ${Date.now()}`, ["doomed"], BOB);
  for (const p of [pa, pb]) {
    await p.goto(`/b/${board.id}`);
    await settled(p);
  }
  await open(pa, "doomed");
  await editDescription(pa);
  await pa.keyboard.type("my unsaved draft");

  await expect(card(pb, "doomed")).toHaveAttribute("aria-selected", "true");
  await pb.keyboard.press("d");
  await settled(pb);
  await expect(pa.getByTestId("deleted-banner")).toContainText(`deleted by ${BOB}`);
  await expect(editorText(pa)).toHaveText("my unsaved draft"); // still editable

  await leave(pa); // nothing is sent: the card is gone
  await pa.keyboard.press("Escape"); // close: the draft goes to the register
  await expect(cardView(pa)).toHaveCount(0);
  await expect(pa.locator("main .message")).toContainText("in the register");
  await pa.keyboard.press("p");
  await settled(pa);
  await expect(card(pa, "doomed")).toHaveCount(1);
  await expect(card(pb, "doomed")).toHaveCount(1);
  await open(pa, "doomed");
  await expect(row(pa, "description")).toHaveText("my unsaved draft");
  await close();
});
