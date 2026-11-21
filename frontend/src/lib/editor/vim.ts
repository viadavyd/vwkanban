// The lazy editor chunk (plan §1.2, §4.1): every CodeMirror / vim import lives here and
// is reached only through load.ts's import(), on the first card open. Grown from the M0
// spike (src/spike/editor.ts, see .local/spike-report.md).

import { deleteCharBackward, history, insertNewline } from "@codemirror/commands";
import { EditorState, type Transaction, type TransactionSpec } from "@codemirror/state";
import { EditorView, drawSelection, keymap } from "@codemirror/view";
import { Vim, getCM, vim } from "@replit/codemirror-vim";
import { EX_COMMANDS, type ExCommand } from "../keys/keymap";
import { snapshotVim, type VimSnapshot } from "./bridge";

export type VimMode = "normal" | "insert" | "visual";

export interface EditorHooks {
  /** `:w`, `:w!`, `:e`, `:e!` */
  onex(command: ExCommand["name"], bang: boolean): void;
  onmode(mode: VimMode): void;
  /** The text changed (the draft). */
  onchange(text: string): void;
  /** `Enter` in INSERT on a single-line field: save and leave. */
  onenter(): void;
}

export interface Editor {
  snapshot(): VimSnapshot;
  text(): string;
  setText(text: string): void;
  focus(): void;
  /** Start in INSERT with the cursor at the end (`a` in card mode). */
  appendMode(): void;
  /** Replays a key typed while the editor was loading (not Esc / Ctrl+C). */
  feed(key: QueuedKey): void;
  destroy(): void;
}

/** What load-time key replay needs of a keydown. */
export interface QueuedKey {
  key: string;
  ctrlKey: boolean;
  shiftKey: boolean;
}

type CM = NonNullable<ReturnType<typeof getCM>>;
const owners = new WeakMap<object, EditorHooks>();
let exDefined = false;

interface ExParams {
  input?: string;
  argString?: string;
}

/** `:w!` arrives as {input: "w!", argString: "!"} (spike report). */
const bangOf = (p: ExParams) =>
  (p.argString ?? "").trimStart().startsWith("!") || /^\s*\w+!/.test(p.input ?? "");

function defineEx(): void {
  if (exDefined) return;
  exDefined = true;
  for (const c of EX_COMMANDS) {
    // This overrides vim's built-in :w (spike point 5).
    Vim.defineEx(c.name, c.short, (cm: CM, params: ExParams) => {
      owners.get(cm as object)?.onex(c.name, bangOf(params));
    });
  }
}

/** Single-line fields: a bare line break (`o`, `O`) is dropped; pasted line breaks become
 * spaces, 1:1, so the selection stays valid. */
const singleLine = EditorState.transactionFilter.of((tr: Transaction) => {
  if (!tr.docChanged || tr.newDoc.lines === 1) return tr;
  const next = tr.newDoc.toString();
  if (next.replace(/\n[ \t]*/g, "") === tr.startState.doc.toString()) return [];
  const spec: TransactionSpec = {
    changes: { from: 0, to: tr.startState.doc.length, insert: next.replace(/\n/g, " ") },
    selection: tr.newSelection,
    effects: tr.effects,
    scrollIntoView: tr.scrollIntoView,
  };
  return spec;
});

const NAMED: Record<string, string> = {
  Escape: "<Esc>",
  Enter: "<CR>",
  Backspace: "<BS>",
  Tab: "<Tab>",
  Delete: "<Del>",
  ArrowLeft: "<Left>",
  ArrowRight: "<Right>",
  ArrowUp: "<Up>",
  ArrowDown: "<Down>",
  " ": "<Space>",
};

function vimKey(k: QueuedKey): string | null {
  if (k.ctrlKey) return k.key.length === 1 ? `<C-${k.key.toLowerCase()}>` : null;
  if (k.key.length === 1 && k.key !== " ") return k.key;
  return NAMED[k.key] ?? null;
}

export function createEditor(
  parent: HTMLElement,
  opts: { doc: string; singleLine: boolean; label: string },
  hooks: EditorHooks,
): Editor {
  defineEx();
  let cm!: CM;
  const view = new EditorView({
    parent,
    state: EditorState.create({
      doc: opts.doc,
      extensions: [
        vim(), // first, so its keymap wins (library docs, spike report)
        drawSelection(),
        history(), // vim's u / Ctrl+R use CodeMirror's history
        opts.singleLine ? singleLine : EditorView.lineWrapping,
        // vim passes Enter through in INSERT: on a single-line field it saves and leaves.
        keymap.of([
          {
            key: "Enter",
            run: (v) => {
              if (!snapshot().insertMode) return false;
              if (!opts.singleLine) return insertNewline(v);
              hooks.onenter();
              return true;
            },
          },
        ]),
        EditorView.updateListener.of((u) => {
          if (u.docChanged) hooks.onchange(u.state.doc.toString());
        }),
        EditorView.contentAttributes.of({ "aria-label": opts.label }),
      ],
    }),
  });
  cm = getCM(view)!;
  owners.set(cm as object, hooks);
  cm.on("vim-mode-change", (e: { mode: string }) => {
    hooks.onmode(
      e.mode === "insert" || e.mode === "replace"
        ? "insert"
        : e.mode === "visual"
          ? "visual"
          : "normal",
    );
  });

  function snapshot(): VimSnapshot {
    const exPrompt = !!view.dom.querySelector(".cm-vim-panel input");
    return snapshotVim((cm as unknown as { state: { vim?: object } }).state.vim, exPrompt);
  }

  return {
    snapshot,
    text: () => view.state.doc.toString(),
    setText(text) {
      view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: text } });
    },
    focus: () => view.focus(),
    appendMode() {
      // End of the document, then `a` (vim `A` only goes to the end of the line).
      view.dispatch({ selection: { anchor: Math.max(view.state.doc.length - 1, 0) } });
      Vim.handleKey(cm, view.state.doc.length ? "a" : "i", "user");
    },
    feed(k) {
      const s = snapshot();
      if (s.insertMode && !k.ctrlKey && k.key.length === 1) {
        view.dispatch(view.state.replaceSelection(k.key));
        return;
      }
      if (s.insertMode && k.key === "Enter") {
        if (opts.singleLine) hooks.onenter();
        else insertNewline(view);
        return;
      }
      if (s.insertMode && k.key === "Backspace") {
        deleteCharBackward(view);
        return;
      }
      const name = vimKey(k);
      if (name) Vim.handleKey(cm, name, "user");
    },
    destroy: () => view.destroy(),
  };
}
