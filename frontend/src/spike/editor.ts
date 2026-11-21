// Lazy chunk: every CodeMirror/vim import lives here and is reached only via import().
import { EditorState, type Transaction, type TransactionSpec } from "@codemirror/state";
import { EditorView, drawSelection } from "@codemirror/view";
import { Vim, getCM, vim } from "@replit/codemirror-vim";
import { snapshotVim, type VimSnapshot } from "./bridge";

export interface ExCall {
  command: "write" | "edit";
  bang: boolean;
  /** Raw params as vim passed them, for the report. */
  raw: { input?: string; argString?: string; args?: string[] };
}

export interface Field {
  view: EditorView;
  snapshot(): VimSnapshot;
  focus(): void;
  blur(): void;
  setDoc(text: string): void;
  /** Feed a key to vim directly (e.g. "A", "<Esc>"). */
  vimKey(key: string): void;
  destroy(): void;
}

type CM = ReturnType<typeof getCM>;
const owners = new WeakMap<object, (call: ExCall) => void>();
let exDefined = false;

interface ExParams {
  input?: string;
  argString?: string;
  args?: string[];
}

function bangOf(p: ExParams): boolean {
  return (p.argString ?? "").trimStart().startsWith("!") || /^\s*\w+!/.test(p.input ?? "");
}

function defineEx(): void {
  if (exDefined) return;
  exDefined = true;
  const handler = (command: ExCall["command"]) => (cm: CM, params: ExParams) => {
    const raw = { input: params.input, argString: params.argString, args: params.args };
    owners.get(cm as object)?.({ command, bang: bangOf(params), raw });
  };
  Vim.defineEx("write", "w", handler("write"));
  Vim.defineEx("edit", "e", handler("edit"));
}

/** Replace newlines 1:1 with spaces, so the selection stays valid. */
const singleLine = EditorState.transactionFilter.of((tr: Transaction) => {
  if (!tr.docChanged || tr.newDoc.lines === 1) return tr;
  const flat = tr.newDoc.toString().replace(/\n/g, " ");
  const spec: TransactionSpec = {
    changes: { from: 0, to: tr.startState.doc.length, insert: flat },
    selection: tr.newSelection,
    effects: tr.effects,
    scrollIntoView: tr.scrollIntoView,
  };
  return spec;
});

export function createField(
  parent: HTMLElement,
  opts: { doc: string; singleLine: boolean; onEx: (call: ExCall) => void },
): Field {
  defineEx();
  const view = new EditorView({
    parent,
    state: EditorState.create({
      doc: opts.doc,
      // vim() must come first so its keymap wins over the others (library docs).
      extensions: [vim(), drawSelection(), opts.singleLine ? singleLine : EditorView.lineWrapping],
    }),
  });
  const cm = getCM(view)!;
  owners.set(cm as object, opts.onEx);
  return {
    view,
    snapshot() {
      const exPrompt = !!view.dom.querySelector(".cm-vim-panel input");
      return snapshotVim((cm as unknown as { state: { vim?: object } }).state.vim, exPrompt);
    },
    focus: () => view.focus(),
    blur: () => view.contentDOM.blur(),
    setDoc(text) {
      view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: text } });
    },
    vimKey: (key) => {
      Vim.handleKey(cm, key, "user");
    },
    destroy: () => view.destroy(),
  };
}
