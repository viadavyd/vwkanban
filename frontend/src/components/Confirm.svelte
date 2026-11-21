<script lang="ts">
  import { pushMode } from "../lib/keys/dispatch";

  let { message, onyes, onno }: { message: string; onyes: () => void; onno: () => void } = $props();

  $effect(() => pushMode("confirm", (action) => (action === "yes" ? onyes() : onno())));
</script>

<div class="backdrop">
  <div class="dialog" role="alertdialog" aria-modal="true" aria-label={message}>
    <p>{message}</p>
    <p class="hint"><kbd>y</kbd> yes · <kbd>n</kbd> no</p>
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
  p {
    margin: 0;
    overflow-wrap: anywhere;
  }
  .hint {
    margin-top: 0.75rem;
    color: #666;
  }
  kbd {
    font: inherit;
    border: 1px solid #888;
    padding: 0 0.3rem;
  }
</style>
