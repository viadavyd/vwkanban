import { describe, expect, it } from "vitest";
import { colorOf, PALETTE, tagColor } from "../src/lib/colors";

describe("colors", () => {
  it("maps status colours and falls back to gray", () => {
    expect(colorOf("red")).toBe(PALETTE.red);
    expect(colorOf("nope")).toBe(PALETTE.gray);
  });

  it("gives a tag the same palette colour every time", () => {
    const all = new Set(Object.values(PALETTE) as string[]);
    for (const t of ["ui", "bug", "backend", "ünïcode", ""]) {
      expect(all.has(tagColor(t))).toBe(true);
      expect(tagColor(t)).toBe(tagColor(t));
    }
    const spread = new Set(Array.from({ length: 50 }, (_, i) => tagColor(`tag${i}`)));
    expect(spread.size).toBeGreaterThan(4);
  });
});
