import { describe, expect, it } from "vitest";
import { columnMove, columnNameError, moveCursor, rowAfterDelete } from "../src/lib/keys/board";

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

describe("column helpers", () => {
  const ids = ["a", "b", "c"];

  it("moves a column past its neighbour, not past the edges", () => {
    expect(columnMove(ids, 1, "left")).toEqual({ to: 0, before_id: "a" });
    expect(columnMove(ids, 1, "right")).toEqual({ to: 2, after_id: "c" });
    expect(columnMove(ids, 0, "left")).toBeNull();
    expect(columnMove(ids, 2, "right")).toBeNull();
    expect(columnMove([], -1, "right")).toBeNull();
  });

  it("checks column names like the server", () => {
    const cols = [
      { id: "a", name: "Todo" },
      { id: "b", name: "Doing" },
    ];
    expect(columnNameError("  ", cols)).toBe("a name is required");
    expect(columnNameError("x".repeat(41), cols)).toMatch(/at most 40/);
    expect(columnNameError("todo", cols)).toBe('a column named "Todo" already exists');
    expect(columnNameError("TODO", cols, "a")).toBeNull(); // renaming itself
    expect(columnNameError("Review", cols)).toBeNull();
  });
});
