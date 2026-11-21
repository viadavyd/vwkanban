import { expect, test, type Page } from "@playwright/test";
import {
  card,
  cardView,
  field,
  mode,
  newCard,
  row,
  seedBoard,
  serverCard,
  settled,
  STATE,
} from "./helpers";

// M5 card mode, keyboard only: the vim fields, the Esc ladder (plan §6), tags and due
// date, children, and the lazy editor chunk. Waits are web-first assertions and
// settled(page) (the sync dot); nothing sleeps. The "vim" tests also run in Firefox.
test.use({ storageState: STATE });

const EDITOR_CHUNK = /\/assets\/vim-[\w-]+\.js$/;

async function open(page: Page, title: string) {
  await expect(card(page, title)).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("i");
  await expect(cardView(page)).toBeVisible();
  await expect(mode(page)).toHaveText("-- CARD --");
}

/** j/k to a row of the card view (title, tags, date, description, child:<id>, add). */
async function to(page: Page, key: string) {
  const rows = cardView(page).locator("[data-row]");
  for (let i = 0; i < 20; i++) {
    const [at, want] = await rows.evaluateAll(
      (els, k) => [
        els.findIndex((e) => e.getAttribute("aria-current") === "true"),
        els.findIndex((e) => (e as HTMLElement).dataset.row === k),
      ],
      key,
    );
    if (want < 0) throw new Error(`no row ${key}`);
    if (at === want) return;
    await page.keyboard.press(want > at ? "j" : "k");
  }
  throw new Error(`can't reach row ${key}`);
}

async function editor(page: Page, vimMode: "NORMAL" | "INSERT") {
  await expect(field(page)).toHaveAttribute("data-ready", "true");
  await expect(mode(page)).toHaveText(`-- ${vimMode} --`);
}

test("vim: the Esc ladder, Esc and Ctrl+C, one level per press", async ({ page }) => {
  const board = await seedBoard(page.request, `M5 ladder ${Date.now()}`, ["ladder"]);
  await page.goto(`/b/${board.id}`);
  await settled(page);
  await open(page, "ladder");
  await to(page, "description");

  for (const back of ["Escape", "Control+c"]) {
    await page.keyboard.press("i");
    await editor(page, "NORMAL");
    // INSERT → NORMAL, staying in the field.
    await page.keyboard.press("i");
    await expect(mode(page)).toHaveText("-- INSERT --");
    await page.keyboard.type(back === "Escape" ? "esc " : "ctrl-c ");
    await page.keyboard.press(back);
    await expect(mode(page)).toHaveText("-- NORMAL --");
    await expect(field(page)).toBeVisible();
    // VISUAL → NORMAL.
    await page.keyboard.press("v");
    await expect(mode(page)).toHaveText("-- VISUAL --");
    await page.keyboard.press(back);
    await expect(mode(page)).toHaveText("-- NORMAL --");
    await expect(field(page)).toBeVisible();
    // A pending operator is cancelled; the field stays (and nothing was deleted).
    await page.keyboard.press("d");
    await page.keyboard.press(back);
    await expect(field(page)).toBeVisible();
    await page.keyboard.press("j");
    await expect(field(page)).toBeVisible();
    // Plain NORMAL: back to the card, and the field is saved.
    await page.keyboard.press(back);
    await expect(field(page)).toHaveCount(0);
    await expect(mode(page)).toHaveText("-- CARD --");
    await settled(page);
  }
  const saved = await serverCard(page.request, board.id, board.cards[0].id);
  expect(saved.description).toBe("ctrl-c esc ");

  // CARD → BOARD → DASHBOARD.
  await page.keyboard.press("Control+c");
  await expect(cardView(page)).toHaveCount(0);
  await expect(mode(page)).toHaveText("-- BOARD --");
  await page.keyboard.press("Escape");
  await expect(mode(page)).toHaveText("-- DASHBOARD --");
});

test("vim: ciw, dd, u and :w in the description", async ({ page }) => {
  const board = await seedBoard(page.request, `M5 vim ${Date.now()}`, ["edit me"]);
  const id = board.cards[0].id;
  await page.goto(`/b/${board.id}`);
  await settled(page);
  await open(page, "edit me");
  await to(page, "description");
  await page.keyboard.press("a"); // INSERT at the end
  await editor(page, "INSERT");
  await page.keyboard.type("one two");
  await page.keyboard.press("Enter");
  await page.keyboard.type("three");
  await page.keyboard.press("Escape");
  await expect(mode(page)).toHaveText("-- NORMAL --");

  await page.keyboard.type("gg");
  await page.keyboard.type("ciwuno");
  await page.keyboard.press("Escape");
  await page.keyboard.type("jdd");
  await page.keyboard.type(":w");
  await page.keyboard.press("Enter");
  await settled(page);
  expect((await serverCard(page.request, board.id, id)).description).toBe("uno two");
  await expect(field(page)).toBeVisible(); // :w stays in the field

  await page.keyboard.press("u"); // vim's undo: the line comes back
  await page.keyboard.press("Escape"); // NORMAL → leave and save
  await expect(mode(page)).toHaveText("-- CARD --");
  await settled(page);
  expect((await serverCard(page.request, board.id, id)).description).toBe("uno two\nthree");
  await expect(row(page, "description")).toHaveText("uno two\nthree");
});

test("tags and due date: saved, shown on the tile; a bad date stays a draft", async ({ page }) => {
  const board = await seedBoard(page.request, `M5 fields ${Date.now()}`, ["fields"]);
  const id = board.cards[0].id;
  await page.goto(`/b/${board.id}`);
  await settled(page);
  await open(page, "fields");

  await to(page, "tags");
  await page.keyboard.press("a");
  await editor(page, "INSERT");
  await page.keyboard.type("ui, bug ui");
  await page.keyboard.press("Enter"); // single line: save and leave
  await expect(mode(page)).toHaveText("-- CARD --");
  await to(page, "date");
  await page.keyboard.press("a");
  await page.keyboard.type("2026-12-24");
  await page.keyboard.press("Enter");
  await settled(page);
  let saved = await serverCard(page.request, board.id, id);
  expect(saved.tags).toEqual(["ui", "bug"]);
  expect(saved.date).toBe("2026-12-24");
  await expect(row(page, "tags").locator(".tag")).toHaveText(["ui", "bug"]);

  // Not a date: not sent; the draft stays on its row with the reason.
  await page.keyboard.press("a");
  await page.keyboard.type("x");
  await page.keyboard.press("Enter");
  await expect(row(page, "date").getByTestId("choice")).toContainText("YYYY-MM-DD");
  await expect(row(page, "date")).toContainText("2026-12-24x");
  await settled(page);
  expect((await serverCard(page.request, board.id, id)).date).toBe("2026-12-24");
  // Fix it from the draft: `i`, drop the x.
  await page.keyboard.press("i");
  await editor(page, "NORMAL");
  await page.keyboard.type("$x");
  await page.keyboard.press("Escape");
  await expect(row(page, "date").getByTestId("choice")).toHaveCount(0);

  await page.keyboard.press("Escape");
  await expect(card(page, "fields").getByTestId("card-meta")).toHaveText(/due 12-24/);
  await expect(card(page, "fields").locator(".tag")).toHaveText(["ui", "bug"]);
});

test("children: [add child], o, O, Space, d and u", async ({ page }) => {
  const board = await seedBoard(page.request, `M5 children ${Date.now()}`, ["parent"]);
  await page.goto(`/b/${board.id}`);
  await settled(page);
  await open(page, "parent");
  const kids = cardView(page).getByTestId("child-title");

  await to(page, "add");
  await page.keyboard.press("i");
  await editor(page, "INSERT");
  await page.keyboard.type("two");
  await page.keyboard.press("Enter");
  await expect(mode(page)).toHaveText("-- CARD --");
  await page.keyboard.press("O"); // above "two"
  await page.keyboard.type("one");
  await page.keyboard.press("Enter");
  await page.keyboard.press("j"); // on "two"
  await page.keyboard.press("o"); // below "two"
  await page.keyboard.type("three");
  await page.keyboard.press("Enter");
  await settled(page);
  await expect(kids).toHaveText(["one", "two", "three"]);

  await page.keyboard.press("Space"); // the row is "three"
  await settled(page);
  const meta = card(page, "parent").getByTestId("card-meta");
  await expect(meta).toHaveText(/☐ 1\/3/);
  await page.keyboard.press("k");
  await page.keyboard.press("d"); // "two"
  await settled(page);
  await expect(kids).toHaveText(["one", "three"]);
  await expect(meta).toHaveText(/☐ 1\/2/);
  await page.keyboard.press("u");
  await settled(page);
  await expect(kids).toHaveText(["one", "two", "three"]);

  // A child's title is a vim field too; `d` on the title row does nothing.
  await to(page, "title");
  await page.keyboard.press("d");
  await expect(cardView(page)).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(meta).toHaveText(/☐ 1\/3/);
});

test("the editor chunk is fetched on the first card open only", async ({ page }) => {
  const chunks: string[] = [];
  page.on("request", (r) => {
    if (EDITOR_CHUNK.test(new URL(r.url()).pathname)) chunks.push(r.url());
  });
  const board = await seedBoard(page.request, `M5 lazy ${Date.now()}`, ["lazy"]);
  await page.goto("/");
  await expect(mode(page)).toHaveText("-- DASHBOARD --");
  await page.goto(`/b/${board.id}`);
  await settled(page);
  expect(chunks).toEqual([]);

  await open(page, "lazy");
  await expect.poll(() => chunks.length).toBe(1);
  await page.keyboard.press("Escape");
  await newCard(page, "second"); // a/A: the chunk is already there
  await open(page, "second");
  await page.keyboard.press("Escape");
  expect(chunks.length).toBe(1);
});
