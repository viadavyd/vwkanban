// Pure decision logic for the FIELD-mode Esc/Ctrl+C bridge (plan §4.2).
// No CodeMirror imports here: this file is in the entry chunk and unit-tested.

export interface VimSnapshot {
  insertMode: boolean;
  visualMode: boolean;
  /** Pending operator, count, register or multi-key prefix. */
  pending: boolean;
  /** The `:` ex prompt is open. */
  exPrompt: boolean;
}

export interface KeyLike {
  key: string;
  ctrlKey: boolean;
  metaKey: boolean;
  altKey: boolean;
  shiftKey: boolean;
}

/** `Esc` or `Ctrl+C` (no other modifiers). */
export function isBackKey(e: KeyLike): boolean {
  if (e.metaKey || e.altKey) return false;
  if (e.key === "Escape") return !e.ctrlKey && !e.shiftKey;
  return e.ctrlKey && !e.shiftKey && e.key.toLowerCase() === "c";
}

/** Leave the field only from plain vim NORMAL with nothing pending. */
export function shouldLeaveField(s: VimSnapshot): boolean {
  return !s.insertMode && !s.visualMode && !s.pending && !s.exPrompt;
}

interface RawInputState {
  operator?: unknown;
  keyBuffer?: unknown[];
  prefixRepeat?: unknown[];
  motionRepeat?: unknown[];
  registerName?: unknown;
}

interface RawVim {
  insertMode?: boolean;
  visualMode?: boolean;
  inputState?: RawInputState;
}

/** Read the bits we need from `getCM(view).state.vim` (shape of @replit/codemirror-vim). */
export function snapshotVim(vim: RawVim | undefined, exPrompt: boolean): VimSnapshot {
  const is = vim?.inputState ?? {};
  const pending =
    !!is.operator ||
    (is.keyBuffer?.length ?? 0) > 0 ||
    (is.prefixRepeat?.length ?? 0) > 0 ||
    (is.motionRepeat?.length ?? 0) > 0 ||
    !!is.registerName;
  return {
    insertMode: !!vim?.insertMode,
    visualMode: !!vim?.visualMode,
    pending,
    exPrompt,
  };
}
