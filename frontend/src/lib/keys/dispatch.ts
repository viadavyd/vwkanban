// One capture-phase keydown listener on window (plan §4.2). It looks up (top mode, key)
// in KEYMAP and calls the handler of whoever pushed that mode. Only bound keys are
// prevented, so typing and browser shortcuts work everywhere else.

import { INPUT_MODES, keyName, lookup, type Action, type Mode } from "./keymap";

type Handler = (action: Action) => void;

interface Layer {
  mode: Mode;
  handler: Handler;
}

const stack: Layer[] = [];

/** Pushes a mode on top; returns a function that removes it (wherever it is). */
export function pushMode(mode: Mode, handler: Handler): () => void {
  const layer: Layer = { mode, handler };
  stack.push(layer);
  return () => {
    const i = stack.indexOf(layer);
    if (i >= 0) stack.splice(i, 1);
  };
}

export function topMode(): Mode | undefined {
  return stack.at(-1)?.mode;
}

function isEditable(t: EventTarget | null): boolean {
  if (!(t instanceof HTMLElement)) return false;
  return t instanceof HTMLInputElement || t instanceof HTMLTextAreaElement || t.isContentEditable;
}

function hasSelection(t: EventTarget | null): boolean {
  if (t instanceof HTMLInputElement || t instanceof HTMLTextAreaElement) {
    return t.selectionStart !== t.selectionEnd;
  }
  return !(window.getSelection()?.isCollapsed ?? true);
}

export function onKeydown(e: KeyboardEvent): void {
  if (e.isComposing) return;
  const layer = stack.at(-1);
  if (!layer) return;
  if (isEditable(e.target) && !INPUT_MODES.has(layer.mode)) return;
  const key = keyName(e);
  if (!key) return;
  if (key === "C-c" && hasSelection(e.target)) return; // let the browser copy
  const action = lookup(layer.mode, key);
  if (!action) return;
  e.preventDefault();
  e.stopPropagation();
  layer.handler(action);
}

/** Installs the listener; returns the uninstall function. */
export function installKeys(): () => void {
  window.addEventListener("keydown", onKeydown, { capture: true });
  return () => window.removeEventListener("keydown", onKeydown, { capture: true });
}
