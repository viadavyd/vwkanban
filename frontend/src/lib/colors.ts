// The 8-colour palette (backend boards/models.py COLORS). Columns pick one; tags get one
// from a hash of their name (plan §0 "Tags": no Tag table).

export const PALETTE = {
  red: "#d32f2f",
  yellow: "#f2c200",
  blue: "#2a3fbf",
  green: "#17806d",
  purple: "#5e2b97",
  orange: "#ef6c00",
  pink: "#d63384",
  gray: "#757575",
} as const;

export type ColorName = keyof typeof PALETTE;

const NAMES = Object.keys(PALETTE) as ColorName[];

export function colorOf(name: string): string {
  return PALETTE[name as ColorName] ?? PALETTE.gray;
}

/** FNV-1a over the tag name → a palette colour; stable across clients. */
export function tagColor(tag: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < tag.length; i++) {
    h ^= tag.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return PALETTE[NAMES[(h >>> 0) % NAMES.length]];
}
