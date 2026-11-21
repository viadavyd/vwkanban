// The single source of truth for keys (plan §4.3). The dispatcher, the help overlay and
// the uniqueness test all read KEYMAP; no other file binds keys.
//
// Modes stack: a screen mode (dashboard, board) with overlays on top (help, prompt,
// confirm). Esc / Ctrl+C always go back exactly one level; the dashboard is the top level.

export type Mode = "dashboard" | "board" | "help" | "prompt" | "confirm";

export type Action =
  | "left"
  | "down"
  | "up"
  | "right"
  | "open"
  | "create"
  | "createAbove"
  | "toggleDone"
  | "rename"
  | "delete"
  | "logout"
  | "help"
  | "back"
  | "submit"
  | "yes"
  | "no";

export interface Binding {
  mode: Mode;
  /** Key names as produced by keyName(): "j", "Q", "?", "Enter", "Esc", "C-c". */
  keys: readonly string[];
  action: Action;
  help: string;
}

export const MODE_LABEL: Record<Mode, string> = {
  dashboard: "Dashboard",
  board: "Board",
  help: "Help",
  prompt: "Prompt",
  confirm: "Confirm",
};

export const KEYMAP: readonly Binding[] = [
  // Dashboard (top level: no Esc binding, there is nothing to go back to)
  { mode: "dashboard", keys: ["h"], action: "left", help: "select the board to the left" },
  { mode: "dashboard", keys: ["j"], action: "down", help: "select the board below" },
  { mode: "dashboard", keys: ["k"], action: "up", help: "select the board above" },
  { mode: "dashboard", keys: ["l"], action: "right", help: "select the board to the right" },
  { mode: "dashboard", keys: ["Enter"], action: "open", help: "open the selected board" },
  { mode: "dashboard", keys: ["a"], action: "create", help: "create a board" },
  { mode: "dashboard", keys: ["r"], action: "rename", help: "rename the selected board" },
  { mode: "dashboard", keys: ["d"], action: "delete", help: "delete the selected board" },
  { mode: "dashboard", keys: ["Q"], action: "logout", help: "log out" },
  { mode: "dashboard", keys: ["?"], action: "help", help: "show this help" },

  // Board (M3a; y p x u i, column keys and H L arrive in M3b and M5)
  { mode: "board", keys: ["h"], action: "left", help: "previous column" },
  { mode: "board", keys: ["j"], action: "down", help: "next card in the column" },
  { mode: "board", keys: ["k"], action: "up", help: "previous card in the column" },
  { mode: "board", keys: ["l"], action: "right", help: "next column" },
  { mode: "board", keys: ["a"], action: "create", help: "new card below the selection" },
  { mode: "board", keys: ["A"], action: "createAbove", help: "new card above the selection" },
  { mode: "board", keys: ["d"], action: "delete", help: "delete the card (with its children)" },
  { mode: "board", keys: ["Space"], action: "toggleDone", help: "toggle done" },
  { mode: "board", keys: ["Esc", "C-c"], action: "back", help: "back to the dashboard" },
  { mode: "board", keys: ["?"], action: "help", help: "show this help" },

  // Overlays
  { mode: "help", keys: ["Esc", "C-c", "?"], action: "back", help: "close help" },
  { mode: "prompt", keys: ["Enter"], action: "submit", help: "save" },
  { mode: "prompt", keys: ["Esc", "C-c"], action: "back", help: "cancel" },
  { mode: "confirm", keys: ["y"], action: "yes", help: "yes" },
  { mode: "confirm", keys: ["n", "Esc", "C-c"], action: "no", help: "no, cancel" },
];

/** Modes whose keys also work while focus is in a text input (the input is the prompt). */
export const INPUT_MODES: ReadonlySet<Mode> = new Set(["prompt"]);

export function bindingsFor(mode: Mode): Binding[] {
  return KEYMAP.filter((b) => b.mode === mode);
}

export function lookup(mode: Mode, key: string): Action | undefined {
  return KEYMAP.find((b) => b.mode === mode && b.keys.includes(key))?.action;
}

export interface KeyLike {
  key: string;
  ctrlKey: boolean;
  metaKey: boolean;
  altKey: boolean;
}

/** A stable name for a keydown, or null for combinations we never bind (Alt, Meta). */
export function keyName(e: KeyLike): string | null {
  if (e.metaKey || e.altKey) return null;
  if (e.key === "Escape") return e.ctrlKey ? null : "Esc";
  if (e.ctrlKey) return e.key.length === 1 ? `C-${e.key.toLowerCase()}` : null;
  if (e.key === " ") return "Space";
  return e.key; // "j", "Q" (shift is in the character), "?", "Enter"
}

/** How a key is shown in help: "C-c" → "Ctrl+C". */
export function displayKey(key: string): string {
  return key.startsWith("C-") ? `Ctrl+${key.slice(2).toUpperCase()}` : key;
}
