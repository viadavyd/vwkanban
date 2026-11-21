// Selection movement in a wrapping grid of tiles (dashboard).

export type Direction = "left" | "down" | "up" | "right";

/** Index after moving; `cols` is the number of tiles per row. */
export function moveInGrid(index: number, dir: Direction, cols: number, count: number): number {
  if (count <= 0) return -1;
  const i = Math.min(Math.max(index, 0), count - 1);
  const c = Math.max(cols, 1);
  switch (dir) {
    case "left":
      return Math.max(i - 1, 0);
    case "right":
      return Math.min(i + 1, count - 1);
    case "up":
      return i - c >= 0 ? i - c : i;
    case "down": {
      if (i + c < count) return i + c;
      // Ragged last row: from a row above it, land on the last tile.
      const lastRow = Math.floor((count - 1) / c);
      return Math.floor(i / c) < lastRow ? count - 1 : i;
    }
  }
}

/** Tiles per row, from the tiles' offsetTop values in DOM order. */
export function columnsFromTops(tops: readonly number[]): number {
  if (tops.length === 0) return 1;
  const n = tops.findIndex((t) => t !== tops[0]);
  return n === -1 ? tops.length : n;
}
