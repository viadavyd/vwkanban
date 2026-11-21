<script lang="ts">
  let {
    title,
    mode,
    pending = "",
    username,
  }: { title?: string; mode: string; pending?: string; username: string } = $props();
</script>

<header>
  <span class="brand">
    <strong>VWKanban</strong>{#if title}<span class="title" data-testid="board-title">
        / {title}
      </span>{/if}
  </span>
  <span class="mode">
    <span data-testid="mode">-- {mode.toUpperCase()} --</span>{#if pending}<span
        class="pending"
        data-testid="pending"
      >
        {pending}
      </span>{/if}
  </span>
  <span class="hint"><kbd>?</kbd> help</span>
  <span data-testid="username">{username}</span>
</header>

<style>
  header {
    display: flex;
    gap: 2rem;
    align-items: center;
    padding: 0.75rem 1rem;
    border-bottom: 2px solid #222;
    background: #fff;
  }
  .brand {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .mode {
    flex: 1;
    text-align: center;
    white-space: nowrap;
  }
  .pending {
    margin-left: 1rem;
    font-weight: bold;
  }
  .hint {
    color: #555;
    white-space: nowrap;
  }
  kbd {
    font: inherit;
    border: 1px solid #888;
    padding: 0 0.3rem;
  }
</style>
