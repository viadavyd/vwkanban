<script lang="ts">
  // FIELD mode (plan §4.2): one CodeMirror vim editor on one card row, mounted while the
  // row is being edited. It pushes the `field` mode with the Esc bridge: Esc / Ctrl+C
  // leave only from plain vim NORMAL; INSERT, VISUAL, a pending operator and the `:`
  // prompt keep them for vim. Keys typed while the chunk loads are replayed in order.
  import { onDestroy, onMount } from "svelte";
  import { pushMode } from "../keys/dispatch";
  import { keyName, lookup, type ExCommand } from "../keys/keymap";
  import { shouldLeaveField } from "./bridge";
  import { loadEditor } from "./load";
  import type { Editor, QueuedKey, VimMode } from "./vim";

  let {
    text,
    singleLine,
    label,
    start,
    onleave,
    onex,
    onmode,
    ondraft,
  }: {
    /** The draft to start from. */
    text: string;
    singleLine: boolean;
    /** Accessible name of the editor ("Description"). */
    label: string;
    /** vim NORMAL, or INSERT at the end (`a`, new cards and children). */
    start: "normal" | "insert";
    /** Esc / Ctrl+C in NORMAL, or Enter in INSERT on a single-line field. */
    onleave: (text: string) => void;
    onex: (command: ExCommand["name"], bang: boolean, text: string) => void;
    onmode: (mode: VimMode) => void;
    ondraft: (text: string) => void;
  } = $props();

  let host: HTMLElement;
  let editor = $state.raw<Editor | null>(null);
  let queued: QueuedKey[] = [];
  let left = false;
  let destroyed = false;

  /** Replaces the editor's text (`:e!`). */
  export function setText(next: string) {
    editor?.setText(next);
  }

  function leave() {
    if (left || !editor) return;
    left = true;
    onleave(editor.text());
  }

  const isBack = (k: QueuedKey) => {
    const name = keyName({ ...k, metaKey: false, altKey: false });
    return !!name && lookup("field", name) === "back";
  };

  /** Keys typed while loading, through the same rules as live ones. */
  function replay(ed: Editor) {
    for (const k of queued) {
      if (left) break;
      if (isBack(k)) {
        if (shouldLeaveField(ed.snapshot())) leave();
        else ed.feed({ key: "Escape", ctrlKey: false, shiftKey: false });
        continue;
      }
      ed.feed(k);
    }
    queued = [];
  }

  const popMode = pushMode("field", () => leave(), {
    field: {
      state: () => (!editor ? "loading" : shouldLeaveField(editor.snapshot()) ? "leave" : "stay"),
      queue: (e) => queued.push({ key: e.key, ctrlKey: e.ctrlKey, shiftKey: e.shiftKey }),
    },
  });

  onMount(async () => {
    const { createEditor } = await loadEditor();
    if (destroyed) return;
    const ed = createEditor(
      host,
      { doc: text, singleLine, label },
      {
        onex: (command, bang) => onex(command, bang, ed.text()),
        onmode,
        onchange: ondraft,
        onenter: () => {
          ed.feed({ key: "Escape", ctrlKey: false, shiftKey: false }); // back to NORMAL first
          leave();
        },
      },
    );
    editor = ed;
    ed.focus();
    if (start === "insert") ed.appendMode();
    onmode(start === "insert" ? "insert" : "normal");
    replay(ed);
  });

  onDestroy(() => {
    destroyed = true;
    popMode();
    editor?.destroy();
    editor = null;
    (document.activeElement as HTMLElement | null)?.blur?.();
  });
</script>

<div class="field" class:single={singleLine} data-testid="vim-field" data-ready={!!editor}>
  {#if !editor}<div class="loading">{text}</div>{/if}
  <div bind:this={host}></div>
</div>

<style>
  .field {
    border: 2px solid #222;
    min-height: 1.6em;
    white-space: pre-wrap;
    font-family: ui-monospace, monospace;
  }
  .loading {
    padding: 0.2rem 0.3rem;
    color: #555;
  }
  .field:not(.single) {
    min-height: 6em;
  }
  .field :global(.cm-editor) {
    outline: none;
  }
  .field :global(.cm-content) {
    font-family: ui-monospace, monospace;
    padding: 0.2rem 0.3rem;
  }
</style>
