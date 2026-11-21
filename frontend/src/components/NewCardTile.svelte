<script lang="ts">
  // The new-card placeholder for a/A (plan §8 M3a: a plain title input until card mode in
  // M5). It pushes the "prompt" mode: Enter saves, Esc/Ctrl+C cancels (one level back).
  // An empty title is discarded, like an empty card in card mode (plan §4.2).
  import { pushMode } from "../lib/keys/dispatch";

  let {
    maxlength,
    onsubmit,
    oncancel,
  }: { maxlength: number; onsubmit: (title: string) => void; oncancel: () => void } = $props();

  let value = $state("");
  let input: HTMLInputElement | undefined = $state();

  $effect(() =>
    pushMode("prompt", (action) => {
      if (action === "submit" && value.trim()) onsubmit(value.trim());
      else oncancel();
    }),
  );

  $effect(() => {
    input?.focus();
    input?.scrollIntoView({ block: "nearest" });
  });
</script>

<div class="tile">
  <input
    bind:this={input}
    bind:value
    {maxlength}
    aria-label="New card title"
    placeholder="New card title"
    autocomplete="off"
  />
</div>

<style>
  .tile {
    border: 2px dashed #222;
    background: #fff;
    padding: 0.4rem 0.5rem;
    outline: 3px solid #222;
    outline-offset: 2px;
  }
  input {
    width: 100%;
    box-sizing: border-box;
    font: inherit;
    border: none;
    outline: none;
    background: transparent;
  }
</style>
