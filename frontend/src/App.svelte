<script lang="ts">
  let api = $state<"…" | "ok" | "down">("…");

  $effect(() => {
    fetch("/api/healthz")
      .then((r) => (api = r.ok ? "ok" : "down"))
      .catch(() => (api = "down"));
  });
</script>

<header>
  <strong>VWKanban</strong>
  <span class="mode">-- DASHBOARD --</span>
  <span data-testid="api-status">api: {api}</span>
</header>
<main>
  <p>Scaffold (M0). Boards arrive in M2.</p>
</main>

<style>
  :global(body) {
    margin: 0;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    background: #fafafa;
    color: #222;
  }
  header {
    display: flex;
    gap: 2rem;
    align-items: center;
    padding: 0.75rem 1rem;
    border-bottom: 2px solid #222;
  }
  .mode {
    flex: 1;
    text-align: center;
  }
  main {
    padding: 1rem;
  }
</style>
