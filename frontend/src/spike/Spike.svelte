<script lang="ts">
  // Throwaway M0 spike: proves the CodeMirror-vim Esc/Ctrl+C bridge (plan §8 M0).
  import { isBackKey, shouldLeaveField } from "./bridge";
  import type { ExCall, Field } from "./editor";

  type FieldId = "title" | "description";
  const fieldIds: FieldId[] = ["title", "description"];
  const initial: Record<FieldId, string> = {
    title: "Spike card title",
    description: "first line of the description\nsecond line\nthird line",
  };

  let mode = $state<"CARD" | "FIELD">("CARD");
  let cursor = $state(0);
  let loaded = $state(false);
  let log = $state<string[]>([]);
  const hosts: Record<FieldId, HTMLElement | undefined> = {
    title: undefined,
    description: undefined,
  };
  const fields: Partial<Record<FieldId, Field>> = {};

  const current = () => fieldIds[cursor];
  const say = (line: string) => (log = [...log, line]);

  function onEx(id: FieldId) {
    return (call: ExCall) => {
      const name = call.command === "write" ? "save" : "revert";
      say(`ex ${id} ${name}${call.bang ? "!" : ""} raw=${JSON.stringify(call.raw)}`);
    };
  }

  async function ensureEditors() {
    if (loaded) return;
    const { createField } = await import("./editor");
    for (const id of fieldIds) {
      hosts[id]!.textContent = "";
      fields[id] = createField(hosts[id]!, {
        doc: initial[id],
        singleLine: id === "title",
        onEx: onEx(id),
      });
    }
    loaded = true;
    say("editor loaded");
  }

  async function enterField(insert: boolean) {
    await ensureEditors();
    const f = fields[current()]!;
    mode = "FIELD";
    f.focus();
    if (insert) f.vimKey("A");
    say(`enter ${current()}`);
  }

  function leaveField(why: string) {
    fields[current()]!.blur();
    mode = "CARD";
    say(`leave ${current()} (${why})`);
  }

  function onKeydown(e: KeyboardEvent) {
    if (mode === "CARD") {
      const k = e.key;
      if (k === "j" || k === "k") {
        cursor = Math.max(0, Math.min(fieldIds.length - 1, cursor + (k === "j" ? 1 : -1)));
      } else if (k === "i" || k === "a") {
        void enterField(k === "a");
      } else return;
      e.preventDefault();
      return;
    }
    const f = fields[current()]!;
    const s = f.snapshot();
    if (isBackKey(e)) {
      const leave = shouldLeaveField(s);
      say(
        `capture ${e.ctrlKey ? "C-c" : "Esc"} insert=${s.insertMode} visual=${s.visualMode}` +
          ` pending=${s.pending} ex=${s.exPrompt} -> ${leave ? "leave" : "pass"}`,
      );
      if (leave) {
        e.preventDefault();
        e.stopPropagation();
        leaveField(e.ctrlKey ? "C-c" : "Esc");
      }
      return;
    }
    if (e.key === "Enter" && current() === "title" && s.insertMode && !s.exPrompt) {
      e.preventDefault();
      e.stopPropagation();
      // Leave INSERT first so the editor is back in NORMAL, then save + leave.
      f.vimKey("<Esc>");
      say("ex title save (enter)");
      leaveField("Enter");
    }
  }

  $effect(() => {
    window.addEventListener("keydown", onKeydown, { capture: true });
    // Test hooks for Playwright.
    (window as unknown as { __spike: object }).__spike = {
      mode: () => mode,
      log: () => log,
      doc: (id: FieldId) => fields[id]?.view.state.doc.toString(),
      vim: (id: FieldId) => fields[id]?.snapshot(),
      focused: (id: FieldId) => fields[id]?.view.hasFocus ?? false,
    };
    return () => window.removeEventListener("keydown", onKeydown, { capture: true });
  });
</script>

<header>
  <strong>vim spike</strong>
  <span data-testid="mode">-- {mode} --</span>
  <span>j/k field · i edit · a append · Esc/Ctrl+C back</span>
</header>

<section class="card">
  {#each fieldIds as id, n (id)}
    <div class="row" class:selected={n === cursor && mode === "CARD"}>
      <label for={id}>{id}</label>
      <div class="field" {id} data-testid={`field-${id}`} bind:this={hosts[id]}>
        <pre>{initial[id]}</pre>
      </div>
    </div>
  {/each}
</section>

<ol data-testid="log">
  {#each log as line, n (n)}
    <li>{line}</li>
  {/each}
</ol>

<style>
  :global(body) {
    margin: 0;
    font-family: ui-monospace, monospace;
  }
  header {
    display: flex;
    gap: 2rem;
    padding: 0.5rem 1rem;
    border-bottom: 2px solid #222;
  }
  .card {
    margin: 1rem;
    border: 2px solid #222;
    padding: 0.5rem;
  }
  .row {
    display: grid;
    grid-template-columns: 8rem 1fr;
    padding: 0.25rem;
  }
  .selected {
    outline: 2px solid #36c;
  }
  .field {
    min-height: 1.5rem;
    border: 1px solid #ccc;
  }
  pre {
    margin: 0;
  }
  ol {
    font-size: 12px;
  }
</style>
