// M0 vim spike: one test per point in plan §8 M0. Results go to .local/spike-report.md.
import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";

type Id = "title" | "description";
const S = (page: Page) => ({
  mode: () => page.evaluate(() => (window as any).__spike.mode() as string),
  log: () => page.evaluate(() => (window as any).__spike.log() as string[]),
  doc: (id: Id) => page.evaluate((i) => (window as any).__spike.doc(i) as string, id),
  vim: (id: Id) => page.evaluate((i) => (window as any).__spike.vim(i), id),
  focused: (id: Id) => page.evaluate((i) => (window as any).__spike.focused(i) as boolean, id),
});

const BACK = { Esc: "Escape", "C-c": "Control+c" } as const;

async function open(page: Page, id: Id = "description") {
  await page.goto("/spike.html");
  if (id === "description") await page.keyboard.press("j");
  await page.keyboard.press("i");
  await expect.poll(() => S(page).mode()).toBe("FIELD");
}

async function lastCapture(page: Page) {
  const log = await S(page).log();
  return log.filter((l) => l.startsWith("capture")).at(-1) ?? "";
}

for (const [name, chord] of Object.entries(BACK)) {
  test(`1/4: capture listener reads vim state before CodeMirror handles ${name}`, async ({
    page,
  }) => {
    await open(page);
    await page.keyboard.press("i");
    expect((await S(page).vim("description")).insertMode).toBe(true);
    await page.keyboard.press(chord);
    // Logged at capture time: still INSERT. Afterwards vim is NORMAL.
    expect(await lastCapture(page)).toContain(`capture ${name} insert=true`);
    expect(await lastCapture(page)).toContain("-> pass");
    expect((await S(page).vim("description")).insertMode).toBe(false);
  });
}

for (const [name, chord] of Object.entries(BACK)) {
  test.describe(`${name}`, () => {
    test(`2/4: ${name} from INSERT, VISUAL and pending d returns to NORMAL in the field`, async ({
      page,
    }) => {
      await open(page);
      const s = S(page);
      // INSERT
      await page.keyboard.press("i");
      await page.keyboard.press(chord);
      expect(await s.mode()).toBe("FIELD");
      expect(await s.vim("description")).toMatchObject({ insertMode: false, visualMode: false });
      // VISUAL
      await page.keyboard.press("v");
      await page.keyboard.press("l");
      expect((await s.vim("description")).visualMode).toBe(true);
      await page.keyboard.press(chord);
      expect(await s.mode()).toBe("FIELD");
      expect((await s.vim("description")).visualMode).toBe(false);
      // pending operator
      const before = await s.doc("description");
      await page.keyboard.press("d");
      expect((await s.vim("description")).pending).toBe(true);
      await page.keyboard.press(chord);
      expect(await s.mode()).toBe("FIELD");
      expect((await s.vim("description")).pending).toBe(false);
      // The cancelled operator must not eat the next motion: `j` just moves.
      await page.keyboard.press("j");
      expect(await s.doc("description")).toBe(before);
      expect(await s.focused("description")).toBe(true);
    });

    test(`3/4: ${name} in plain NORMAL leaves the field`, async ({ page }) => {
      await open(page);
      await page.keyboard.press(chord);
      expect(await S(page).mode()).toBe("CARD");
      expect(await S(page).focused("description")).toBe(false);
      expect(await lastCapture(page)).toContain("-> leave");
    });
  });
}

test("2b: Esc inside the : ex prompt closes the prompt, not the field", async ({ page }) => {
  await open(page);
  await page.keyboard.press(":");
  await page.keyboard.press("Escape");
  expect(await S(page).mode()).toBe("FIELD");
  expect(await lastCapture(page)).toContain("ex=true");
});

test("5: :w, :w! and :e! reach defineEx handlers with the bang flag", async ({ page }) => {
  await open(page);
  for (const cmd of ["w", "w!", "e!"]) {
    await page.keyboard.type(`:${cmd}`);
    await page.keyboard.press("Enter");
  }
  const ex = (await S(page).log()).filter((l) => l.startsWith("ex "));
  expect(ex[0]).toMatch(/^ex description save raw=/);
  expect(ex[1]).toMatch(/^ex description save! raw=/);
  expect(ex[2]).toMatch(/^ex description revert! raw=/);
  expect(await S(page).mode()).toBe("FIELD");
  console.log("ex params:", ex.join("\n"));
});

test("6: single-line title never contains a newline", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await open(page, "title");
  const s = S(page);
  await page.keyboard.press("o"); // open line below -> must not add \n
  await page.keyboard.type("typed");
  await page.keyboard.press("Escape");
  expect(await s.doc("title")).not.toContain("\n");
  await page.keyboard.press("O");
  await page.keyboard.press("Escape");
  expect(await s.doc("title")).not.toContain("\n");
  // Paste multi-line text in INSERT.
  await page.evaluate(() => navigator.clipboard.writeText("a\nb\nc"));
  await page.keyboard.press("A");
  await page.keyboard.press("ControlOrMeta+v");
  expect(await s.doc("title")).not.toContain("\n");
  expect(await s.doc("title")).toContain("a b c");
  // Enter in INSERT = save and leave.
  await page.keyboard.press("Enter");
  expect(await s.mode()).toBe("CARD");
  expect(await s.doc("title")).not.toContain("\n");
  expect(await s.log()).toContain("ex title save (enter)");
});

test("7: editor chunk is lazy (not fetched until card edit) and its size is reported", async ({
  page,
}) => {
  const js: string[] = [];
  page.on("request", (r) => r.url().endsWith(".js") && js.push(r.url()));
  await page.goto("/spike.html");
  await page.waitForLoadState("networkidle");
  const atLoad = js.length;
  await page.keyboard.press("i");
  await expect.poll(() => S(page).mode()).toBe("FIELD");
  expect(js.length).toBeGreaterThan(atLoad);
  const report = JSON.parse(readFileSync("dist-spike/size-report.json", "utf8"));
  expect(report.entry.hasCodeMirror).toBe(false);
  console.log(
    `entry ${(report.entry.gzip / 1024).toFixed(1)} KB gz, lazy ${(report.lazyGzipTotal / 1024).toFixed(1)} KB gz`,
  );
});
