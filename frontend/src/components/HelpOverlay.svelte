<script lang="ts">
  // Rendered from keymap.ts, so help can't drift from the real bindings.
  import { pushMode } from "../lib/keys/dispatch";
  import {
    bindingsFor,
    displayKey,
    MODE_LABEL,
    PREFIX,
    SUBMODES,
    type Mode,
  } from "../lib/keys/keymap";

  let { mode, onclose }: { mode: Mode; onclose: () => void } = $props();

  const sections = $derived([mode, ...(SUBMODES[mode] ?? []), "help"] as Mode[]);
  // A prefix mode's keys read as "s a"; its Esc is shown as is.
  const shown = (m: Mode, k: string) =>
    PREFIX[m] && k !== "Esc" && k !== "C-c" ? `${PREFIX[m]} ${k}` : displayKey(k);

  $effect(() => pushMode("help", () => onclose()));
</script>

<div class="backdrop">
  <div class="dialog" role="dialog" aria-modal="true" aria-label="Help">
    {#each sections as m (m)}
      <h2>{MODE_LABEL[m]}</h2>
      <table>
        <tbody>
          {#each bindingsFor(m) as b (b.keys.join(" "))}
            <tr>
              <td class="keys">
                {#each b.keys as k, i (k)}{#if i > 0}
                    /
                  {/if}<kbd>{shown(m, k)}</kbd>{/each}
              </td>
              <td>{b.help}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/each}
  </div>
</div>

<style>
  .backdrop {
    position: fixed;
    inset: 0;
    background: rgb(0 0 0 / 0.25);
    display: grid;
    place-items: center;
    padding: 1rem;
  }
  .dialog {
    width: min(32rem, 100%);
    max-height: calc(100vh - 2rem);
    overflow: auto;
    background: #fff;
    border: 2px solid #222;
    padding: 1rem 1.5rem 1.5rem;
  }
  h2 {
    font-size: 1rem;
    margin: 0.75rem 0 0.5rem;
  }
  table {
    border-collapse: collapse;
    width: 100%;
  }
  td {
    padding: 0.2rem 0;
    vertical-align: top;
  }
  .keys {
    padding-right: 1.5rem;
    white-space: nowrap;
  }
  kbd {
    font: inherit;
    border: 1px solid #888;
    padding: 0 0.3rem;
  }
</style>
