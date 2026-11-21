import { describe, expect, it } from "vitest";
import { moveCursor, rowAfterDelete } from "../src/lib/keys/board";

describe("board cursor", () => {
  const lengths = [3, 0, 5];

  it("moves within a column and stops at its ends", () => {
    expect(moveCursor(lengths, { col: 0, row: 0 }, "down")).toEqual({ col: 0, row: 1 });
    expect(moveCursor(lengths, { col: 0, row: 2 }, "down")).toEqual({ col: 0, row: 2 });
    expect(moveCursor(lengths, { col: 0, row: 0 }, "up")).toEqual({ col: 0, row: 0 });
    expect(moveCursor(lengths, { col: 1, row: -1 }, "down")).toEqual({ col: 1, row: -1 });
  });

  it("moves between columns, selecting empty ones, keeping the wanted row", () => {
    expect(moveCursor(lengths, { col: 0, row: 2 }, "right")).toEqual({ col: 1, row: -1 });
    expect(moveCursor(lengths, { col: 1, row: -1 }, "right", 2)).toEqual({ col: 2, row: 2 });
    expect(moveCursor(lengths, { col: 2, row: 4 }, "left", 4)).toEqual({ col: 1, row: -1 });
    expect(moveCursor(lengths, { col: 0, row: 4 }, "right", 4)).toEqual({ col: 1, row: -1 });
    expect(moveCursor([3, 5], { col: 1, row: 4 }, "left")).toEqual({ col: 0, row: 2 });
    expect(moveCursor(lengths, { col: 0, row: 0 }, "left")).toEqual({ col: 0, row: 0 });
    expect(moveCursor(lengths, { col: 2, row: 0 }, "right")).toEqual({ col: 2, row: 0 });
  });

  it("handles a board without columns", () => {
    expect(moveCursor([], { col: 0, row: 0 }, "down")).toEqual({ col: -1, row: -1 });
  });

  it("selects the next card after a delete, else the previous", () => {
    expect(rowAfterDelete(1, 3)).toBe(1);
    expect(rowAfterDelete(2, 3)).toBe(1);
    expect(rowAfterDelete(0, 1)).toBe(-1);
  });
});
