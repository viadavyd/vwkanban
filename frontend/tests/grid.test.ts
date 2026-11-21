import { describe, expect, it } from "vitest";
import { columnsFromTops, moveInGrid } from "../src/lib/keys/grid";

// 3 columns, 8 tiles:
//  0 1 2
//  3 4 5
//  6 7
describe("moveInGrid", () => {
  const m = (i: number, d: Parameters<typeof moveInGrid>[1]) => moveInGrid(i, d, 3, 8);

  it("moves left and right linearly, clamped at the ends", () => {
    expect(m(0, "left")).toBe(0);
    expect(m(2, "right")).toBe(3);
    expect(m(7, "right")).toBe(7);
  });

  it("moves up and down by a row", () => {
    expect(m(1, "down")).toBe(4);
    expect(m(4, "down")).toBe(7);
    expect(m(4, "up")).toBe(1);
    expect(m(1, "up")).toBe(1);
  });

  it("lands on the last tile when the row below is short", () => {
    expect(m(5, "down")).toBe(7);
    expect(m(7, "down")).toBe(7);
    expect(m(6, "down")).toBe(6);
  });

  it("handles empty and single-column grids", () => {
    expect(moveInGrid(0, "down", 3, 0)).toBe(-1);
    expect(moveInGrid(0, "down", 1, 3)).toBe(1);
    expect(moveInGrid(5, "up", 3, 3)).toBe(2); // out-of-range index is clamped first
  });
});

describe("columnsFromTops", () => {
  it("counts the tiles in the first row", () => {
    expect(columnsFromTops([0, 0, 0, 120, 120])).toBe(3);
    expect(columnsFromTops([0, 0])).toBe(2);
    expect(columnsFromTops([])).toBe(1);
  });
});
