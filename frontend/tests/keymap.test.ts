import { describe, expect, it } from "vitest";
import { KEYMAP, keyName, lookup, MODE_LABEL, type Mode } from "../src/lib/keys/keymap";

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
