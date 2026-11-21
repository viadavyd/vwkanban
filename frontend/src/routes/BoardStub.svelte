<script lang="ts">
  // M2 placeholder for the board view (M3a): proves Enter / Esc between the two levels.
  import HelpOverlay from "../components/HelpOverlay.svelte";
  import TopBar from "../components/TopBar.svelte";
  import type { User } from "../lib/api/auth";
  import { getBoard, type BoardDetail } from "../lib/api/boards";
  import { ApiError } from "../lib/api/client";
  import { pushMode } from "../lib/keys/dispatch";

  let {
    id,
    user,
    onback,
    onloggedout,
  }: { id: string; user: User; onback: () => void; onloggedout: () => void } = $props();

  let detail = $state<BoardDetail | null>(null);
  let help = $state(false);
  let message = $state("");

  async function load(boardId: string) {
    try {
      detail = await getBoard(boardId);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) onloggedout();
      else if (e instanceof ApiError && (e.status === 404 || e.status === 422)) onback();
      else message = e instanceof ApiError ? e.message : "Something went wrong";
    }
  }

  $effect(() => {
    load(id);
  });

  $effect(() =>
    pushMode("board", (action) => {
      if (action === "back") onback();
      else if (action === "help") help = true;
    }),
  );
</script>

<TopBar mode="board" title={detail?.board.title ?? "…"} username={user.username} />

<main>
  {#if detail}
    <p>
      Columns: {detail.statuses.map((s) => s.name).join(" · ")}. The board view arrives in M3a.
    </p>
    <p class="muted">Press <kbd>Esc</kbd> to go back to the dashboard.</p>
  {/if}
  <p class="message" role="status">{message}</p>
</main>

{#if help}
  <HelpOverlay mode="board" onclose={() => (help = false)} />
{/if}

<style>
  main {
    padding: 1.25rem 1rem;
  }
  .muted {
    color: #666;
  }
  .message {
    color: #b00020;
  }
  kbd {
    font: inherit;
    border: 1px solid #888;
    padding: 0 0.3rem;
  }
</style>
