import { describe, expect, it } from "vitest";
import {
  EX_COMMANDS,
  HELP_SECTIONS,
  helpKey,
  helpRows,
  KEYMAP,
  keyName,
  lookup,
  MODE_LABEL,
  PREFIX,
  type HelpScreen,
  type Mode,
} from "../src/lib/keys/keymap";

const modes = Object.keys(MODE_LABEL) as Mode[];

const ev = (
  key: string,
  mods: Partial<Record<"ctrlKey" | "metaKey" | "altKey", boolean>> = {},
) => ({
  key,
  ctrlKey: false,
  metaKey: false,
  altKey: false,
  ...mods,
});

describe("keymap", () => {
  it("has no duplicate (mode, key)", () => {
    const seen = new Set<string>();
    for (const b of KEYMAP) {
      for (const k of b.keys) {
        const id = `${b.mode} ${k}`;
        expect(seen.has(id), `duplicate ${id}`).toBe(false);
        seen.add(id);
      }
    }
  });

  it("documents every binding", () => {
    for (const b of KEYMAP) {
      expect(b.keys.length, `${b.mode} ${b.action}`).toBeGreaterThan(0);
      expect(b.help.trim(), `${b.mode} ${b.keys.join(",")}`).not.toBe("");
    }
  });

  it("binds every mode", () => {
    for (const m of modes)
      expect(
        KEYMAP.some((b) => b.mode === m),
        m,
      ).toBe(true);
  });

  it("goes back one level with Esc and Ctrl+C from every mode below the dashboard", () => {
    for (const m of modes) {
      if (m === "dashboard") {
        expect(lookup(m, "Esc")).toBeUndefined();
        expect(lookup(m, "C-c")).toBeUndefined();
        continue;
      }
      const back = m === "confirm" ? "no" : "back";
      expect(lookup(m, "Esc"), m).toBe(back);
      expect(lookup(m, "C-c"), m).toBe(back);
    }
  });

  it("binds the M2 dashboard keys", () => {
    const keys = KEYMAP.filter((b) => b.mode === "dashboard").flatMap((b) => b.keys);
    expect(keys.sort()).toEqual(["?", "Enter", "Q", "a", "d", "h", "j", "k", "l", "r"].sort());
  });

  it("binds the M3a, M3b, M4 and M6 board keys", () => {
    const keys = KEYMAP.filter((b) => b.mode === "board").flatMap((b) => b.keys);
    expect(keys.sort()).toEqual(
      [
        ...["?", "A", "C-c", "Esc", "Space", "a", "d", "h", "j", "k", "l", "i"],
        ...["y", "p", "x", "u", "s", "H", "L"],
        "M",
        ...["E", "I"],
      ].sort(),
    );
  });

  it("binds CSV export and import on the board (M6)", () => {
    expect(lookup("board", "E")).toBe("exportCsv");
    expect(lookup("board", "I")).toBe("importCsv");
  });

  it("binds the column commands under the s prefix", () => {
    expect(lookup("board", "s")).toBe("columnPrefix");
    expect(PREFIX.column).toBe("s");
    expect(HELP_SECTIONS.board).toContain("column");
    const keys = KEYMAP.filter((b) => b.mode === "column").flatMap((b) => b.keys);
    expect(keys.sort()).toEqual(["C-c", "Esc", "a", "c", "d", "r"].sort());
  });

  it("binds the members overlay (M)", () => {
    expect(lookup("board", "M")).toBe("members");
    const keys = KEYMAP.filter((b) => b.mode === "members").flatMap((b) => b.keys);
    expect(keys.sort()).toEqual(["C-c", "Esc", "a", "d", "j", "k"].sort());
  });

  it("binds card mode (M5) and only the way back in a field", () => {
    expect(lookup("board", "i")).toBe("open");
    const card = KEYMAP.filter((b) => b.mode === "card").flatMap((b) => b.keys);
    expect(card.sort()).toEqual(
      ["?", "C-c", "Esc", "O", "Space", "a", "d", "i", "j", "k", "o", "u"].sort(),
    );
    const field = KEYMAP.filter((b) => b.mode === "field").flatMap((b) => b.keys);
    expect(field.sort()).toEqual(["C-c", "Esc"]);
    expect(HELP_SECTIONS.card).toContain("field");
  });

  it("documents the ex commands (:w, :e) with and without !", () => {
    expect(EX_COMMANDS.map((c) => c.short)).toEqual(["w", "e"]);
    for (const c of EX_COMMANDS) {
      expect(c.name.startsWith(c.short)).toBe(true);
      expect(c.help.trim()).not.toBe("");
      expect(c.bangHelp.trim()).not.toBe("");
    }
  });

  it("shows every binding and ex command in some screen's help (M7)", () => {
    const shown = new Set<string>();
    for (const screen of Object.keys(HELP_SECTIONS) as HelpScreen[])
      for (const m of HELP_SECTIONS[screen])
        for (const row of helpRows(m)) for (const k of row.keys) shown.add(`${m} ${k}`);
    const missing = [
      ...KEYMAP.flatMap((b) => b.keys.map((k) => `${b.mode} ${helpKey(b.mode, k)}`)),
      ...EX_COMMANDS.flatMap((c) => [`field :${c.short}`, `field :${c.short}!`]),
    ].filter((id) => !shown.has(id));
    expect(missing).toEqual([]);
    const sections = Object.values(HELP_SECTIONS).flat();
    for (const m of modes) expect(sections, m).toContain(m);
  });

  it("starts each screen's help with the screen and ends it with help's own keys", () => {
    for (const [screen, sections] of Object.entries(HELP_SECTIONS)) {
      expect(sections[0]).toBe(screen);
      expect(sections.at(-1)).toBe("help");
      expect(new Set(sections).size, screen).toBe(sections.length);
    }
    // The overlays each screen can open (Prompt.svelte, Confirm.svelte).
    for (const screen of ["dashboard", "board"] as const)
      expect(HELP_SECTIONS[screen]).toEqual(expect.arrayContaining(["prompt", "confirm"]));
  });

  it("formats help keys: prefixes, Ctrl and ex commands", () => {
    expect(helpKey("column", "a")).toBe("s a");
    expect(helpKey("column", "Esc")).toBe("Esc");
    expect(helpKey("board", "C-c")).toBe("Ctrl+C");
    expect(helpRows("field").flatMap((r) => r.keys)).toEqual([
      "Esc",
      "Ctrl+C",
      ":w",
      ":w!",
      ":e",
      ":e!",
    ]);
  });

  it("names keys", () => {
    expect(keyName(ev("j"))).toBe("j");
    expect(keyName(ev("Q"))).toBe("Q");
    expect(keyName(ev("?"))).toBe("?");
    expect(keyName(ev("Escape"))).toBe("Esc");
    expect(keyName(ev(" "))).toBe("Space");
    expect(keyName(ev("c", { ctrlKey: true }))).toBe("C-c");
    expect(keyName(ev("C", { ctrlKey: true }))).toBe("C-c");
    expect(keyName(ev("a", { metaKey: true }))).toBeNull();
    expect(keyName(ev("a", { altKey: true }))).toBeNull();
  });
});
