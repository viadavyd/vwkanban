<script lang="ts">
  // A plain-input prompt (plan §4.2: prompts are not vim). Enter saves, Esc/Ctrl+C cancels;
  // both go through the "prompt" mode of the key dispatcher.
  import { pushMode } from "../lib/keys/dispatch";

  let {
    label,
    initial = "",
    maxlength,
    onsubmit,
    oncancel,
  }: {
    label: string;
    initial?: string;
    maxlength?: number;
    /** Returns an error message to show, or nothing on success. */
    onsubmit: (value: string) => Promise<string | void>;
    oncancel: () => void;
  } = $props();

  // svelte-ignore state_referenced_locally (the initial value is read once)
  let value = $state(initial);
  let error = $state("");
  let busy = $state(false);
  let input: HTMLInputElement | undefined = $state();

  async function submit() {
    if (busy) return;
    busy = true;
    error = (await onsubmit(value)) ?? "";
    busy = false;
    if (error) input?.focus();
  }

  $effect(() =>
    pushMode("prompt", (action) => {
      if (action === "submit") submit();
      else if (action === "back") oncancel();
    }),
  );

  $effect(() => {
    input?.focus();
    input?.select();
  });
</script>

<div class="backdrop">
  <div class="dialog" role="dialog" aria-modal="true" aria-label={label}>
    <label>
      <span>{label}</span>
      <input bind:this={input} bind:value {maxlength} disabled={busy} spellcheck="false" />
    </label>
    <p class="error" role="alert">{error}</p>
    <p class="hint">Enter save · Esc cancel</p>
  </div>
</div>

<style>
  .backdrop {
    position: fixed;
    inset: 0;
    background: rgb(0 0 0 / 0.25);
    display: grid;
    place-items: start center;
    padding-top: 20vh;
  }
  .dialog {
    width: min(28rem, calc(100vw - 2rem));
    background: #fff;
    border: 2px solid #222;
    padding: 1.25rem 1.5rem;
  }
  label {
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
  }
  input {
    font: inherit;
    padding: 0.5rem 0.6rem;
    border: 2px solid #222;
  }
  input:focus {
    outline: 3px solid #4a7dff;
    outline-offset: 1px;
  }
  .error {
    min-height: 1.2em;
    margin: 0.5rem 0 0;
    color: #b00020;
    font-size: 0.9rem;
  }
  .hint {
    margin: 0.25rem 0 0;
    color: #666;
    font-size: 0.85rem;
  }
</style>
