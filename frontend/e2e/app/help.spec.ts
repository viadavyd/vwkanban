import { expect, test, type Page } from "@playwright/test";
import { HELP_SECTIONS, helpRows, MODE_LABEL, type HelpScreen } from "../../src/lib/keys/keymap";
import { cardView, mode, seedBoard, settled, STATE } from "./helpers";

// M7: `?` on each screen shows exactly the rows keymap.ts defines for it (every section,
// every key, every help text). With tests/keymap.test.ts (the sections cover all of
// KEYMAP and the ex commands), this proves the overlay shows every key.

test.use({ storageState: STATE });

const helpDialog = (page: Page) => page.getByRole("dialog", { name: "Help" });

async function expectHelp(page: Page, screen: HelpScreen) {
  await page.keyboard.press("?");
  const help = helpDialog(page);
  await expect(help).toBeVisible();
  const sections = help.locator("[data-help-section]");
  await expect(sections).toHaveCount(HELP_SECTIONS[screen].length);
  for (const [i, m] of HELP_SECTIONS[screen].entries()) {
    const section = sections.nth(i);
    await expect(section).toHaveAttribute("data-help-section", m);
    await expect(section.getByRole("heading")).toHaveText(MODE_LABEL[m]);
    const want = helpRows(m);
    const rows = section.locator("[data-help-row]");
    await expect(rows).toHaveCount(want.length);
    for (const [j, row] of want.entries()) {
      await expect(rows.nth(j).locator("kbd")).toHaveText(row.keys);
      await expect(rows.nth(j).locator(".what")).toHaveText(row.help);
    }
  }
  await page.keyboard.press("Escape");
  await expect(help).toBeHidden();
}

test("help lists every key of the dashboard, the board and the card view", async ({
  page,
  request,
}) => {
  const board = await seedBoard(request, `M7 help ${Date.now()}`, ["one card"]);

  await page.goto("/");
  await expect(mode(page)).toHaveText(/DASHBOARD/);
  await expectHelp(page, "dashboard");

  await page.goto(`/b/${board.id}`);
  await settled(page);
  await expectHelp(page, "board");
  await expect(mode(page)).toHaveText(/BOARD/); // Esc closed only the help

  await page.keyboard.press("i");
  await expect(cardView(page)).toBeVisible();
  await expectHelp(page, "card");
  await expect(cardView(page)).toBeVisible(); // still in card mode
  await page.keyboard.press("Escape");
  await expect(cardView(page)).toBeHidden();
  await settled(page);
});
