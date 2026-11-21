// Board selection (plan §4.3): h/l move between columns (empty ones too) and keep the row,
// clamped to the column; j/k move within a column and stop at its ends.

import type { Direction } from "./grid";

export interface Cursor {
  col: number;
  /** -1 = the column is empty */
  row: number;
}

export function clampRow(row: number, length: number): number {
  return length === 0 ? -1 : Math.min(Math.max(row, 0), length - 1);
}

/** `lengths[i]` = number of cards in column i. `want` = the row h/l try to keep. */
export function moveCursor(lengths: number[], cur: Cursor, dir: Direction, want = cur.row): Cursor {
  if (lengths.length === 0) return { col: -1, row: -1 };
  const col = Math.min(Math.max(cur.col, 0), lengths.length - 1);
  switch (dir) {
    case "left":
    case "right": {
      const next = Math.min(Math.max(col + (dir === "left" ? -1 : 1), 0), lengths.length - 1);
      return { col: next, row: clampRow(want, lengths[next]) };
    }
    case "up":
    case "down": {
      const row = clampRow(cur.row + (dir === "up" ? -1 : 1), lengths[col]);
      return { col, row };
    }
  }
}

/** Where the selection goes after the card at `row` is deleted: the next card, else the
 * previous one, else none. `length` is the column's length before the delete. */
export function rowAfterDelete(row: number, length: number): number {
  return clampRow(row, length - 1);
}
