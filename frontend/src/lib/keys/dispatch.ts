// One capture-phase keydown listener on window (plan §4.2). It looks up (top mode, key)
// in KEYMAP and calls the handler of whoever pushed that mode. Only bound keys are
// prevented, so typing and browser shortcuts work everywhere else.
//
// FIELD mode (a CodeMirror vim editor) is the exception: the listener sees each key before
// CodeMirror does and binds only the way back. Esc / Ctrl+C leave the field only when the
// field says so (plain vim NORMAL, nothing pending, no `:` prompt); otherwise the key goes
// on to vim, which returns to NORMAL. One level per press. While the editor chunk is
// still loading, every key is captured and handed to the field to replay once it is up,
// so keys typed right after `a` are not lost.

import { INPUT_MODES, keyName, lookup, type Action, type Mode } from "./keymap";

type Handler = (action: Action) => void;

/** What a `field` layer tells the dispatcher. */
export interface FieldBridge {
  /** "loading" until the editor is mounted; then whether a back key leaves the field. */
  state(): "loading" | "leave" | "stay";
  /** While loading: a key to replay, in order, once the editor is up. */
  queue(e: KeyboardEvent): void;
}

interface Layer {
  mode: Mode;
  handler: Handler;
  field?: FieldBridge;
}

const stack: Layer[] = [];

/** Pushes a mode on top; returns a function that removes it (wherever it is). A `field`
 * mode passes its bridge. */
export function pushMode(
  mode: Mode,
  handler: Handler,
  opts: { field?: FieldBridge } = {},
): () => void {
  const layer: Layer = { mode, handler, field: opts.field };
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

const MODIFIERS = new Set(["Shift", "Control", "Alt", "Meta", "CapsLock"]);

function stop(e: KeyboardEvent): void {
  e.preventDefault();
  e.stopPropagation();
}

function fieldKey(layer: Layer, field: FieldBridge, e: KeyboardEvent): void {
  const state = field.state();
  if (state === "loading") {
    if (MODIFIERS.has(e.key) || e.metaKey || e.altKey) return;
    stop(e);
    field.queue(e);
    return;
  }
  const key = keyName(e);
  if (!key || lookup(layer.mode, key) !== "back" || state !== "leave") return; // vim's
  stop(e);
  layer.handler("back");
}

export function onKeydown(e: KeyboardEvent): void {
  if (e.isComposing) return;
  const layer = stack.at(-1);
  if (!layer) return;
  if (layer.field) return fieldKey(layer, layer.field, e);
  if (isEditable(e.target) && !INPUT_MODES.has(layer.mode)) return;
  const key = keyName(e);
  if (!key) return;
  if (key === "C-c" && hasSelection(e.target)) return; // let the browser copy
  const action = lookup(layer.mode, key);
  if (!action) return;
  stop(e);
  layer.handler(action);
}

/** Installs the listener; returns the uninstall function. */
export function installKeys(): () => void {
  window.addEventListener("keydown", onKeydown, { capture: true });
  return () => window.removeEventListener("keydown", onKeydown, { capture: true });
}
