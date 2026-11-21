<script lang="ts">
  // Board view per .local/drawing/board.png and plan §4.4: columns of card tiles,
  // keyboard-first (keys in keymap.ts, board mode).
  import Column from "../components/Column.svelte";
  import HelpOverlay from "../components/HelpOverlay.svelte";
  import TopBar from "../components/TopBar.svelte";
  import type { User } from "../lib/api/auth";
  import { getBoard, type BoardDetail } from "../lib/api/boards";
  import { ApiError } from "../lib/api/client";
  import { clampRow, moveCursor } from "../lib/keys/board";
  import { pushMode } from "../lib/keys/dispatch";
  import type { Action } from "../lib/keys/keymap";
  import type { BoardView } from "../lib/sync/ops";
  import { BoardStore } from "../lib/sync/store";

  let {
    id,
    user,
    onback,
    onloggedout,
  }: { id: string; user: User; onback: () => void; onloggedout: () => void } = $props();

  let title = $state("…");
  let store: BoardStore | null = null;
  // Raw: the view is rebuilt as a whole; unchanged cards keep their identity.
  let view = $state.raw<BoardView | null>(null);
  let overlay = $state<"help" | null>(null);
  let message = $state("");

  // Selection: a column and a card in it (by id, so it survives inserts above it).
  // `want` is the row h/l try to keep.
  let selCol = $state(0);
  let selId = $state<string | null>(null);
  let want = $state(0);

  const statuses = $derived(view?.statuses ?? []);
  const colCards = $derived(view && statuses[selCol] ? view.columns.get(statuses[selCol].id)! : []);
  // The selected row; if the card went away (e.g. a resync), fall back to the kept row.
  const selRow = $derived.by(() => {
    const i = selId ? colCards.findIndex((c) => c.id === selId) : -1;
    return i >= 0 ? i : clampRow(want, colCards.length);
  });
  const selectedId = $derived(selRow >= 0 ? (colCards[selRow]?.id ?? null) : null);

  function fail(e: unknown) {
    if (e instanceof ApiError && e.status === 401) onloggedout();
    else if (e instanceof ApiError && (e.status === 404 || e.status === 422)) onback();
    else message = e instanceof ApiError ? e.message : "Something went wrong";
  }

  async function load(boardId: string) {
    let detail: BoardDetail;
    try {
      detail = await getBoard(boardId);
    } catch (e) {
      return fail(e);
    }
    title = detail.board.title;
    store = new BoardStore(boardId, detail, {
      onchange: (v) => (view = v),
      onmessage: (m) => (message = m),
      onloggedout,
      ongone: onback,
      load: () => getBoard(boardId),
    });
    view = store.view;
  }

  function select(col: number, row: number) {
    selCol = col;
    const cards = view?.columns.get(statuses[col]?.id) ?? [];
    selId = row >= 0 ? (cards[row]?.id ?? null) : null;
  }

  function move(dir: "left" | "down" | "up" | "right") {
    if (!view) return;
    const lengths = statuses.map((s) => view!.columns.get(s.id)!.length);
    const next = moveCursor(lengths, { col: selCol, row: selRow }, dir, want);
    if (dir === "up" || dir === "down") want = Math.max(next.row, 0);
    select(next.col, next.row);
  }

  function selectCard(cardId: string) {
    if (!view) return;
    const col = statuses.findIndex((s) => view!.columns.get(s.id)!.some((c) => c.id === cardId));
    if (col < 0) return;
    selCol = col;
    selId = cardId;
    want = view.columns.get(statuses[col].id)!.findIndex((c) => c.id === cardId);
  }

  function onkey(action: Action) {
    message = "";
    switch (action) {
      case "left":
      case "down":
      case "up":
      case "right":
        return move(action);
      case "back":
        return onback();
      case "help":
        overlay = "help";
        return;
    }
  }

  $effect(() => {
    load(id);
    return () => store?.close();
  });

  $effect(() => pushMode("board", (a) => onkey(a)));

  // Keep the selection in view (columns scroll on their own; the board scrolls sideways).
  $effect(() => {
    const target = selectedId
      ? document.querySelector(`[data-card="${selectedId}"]`)
      : statuses[selCol] && document.querySelector(`[data-column="${statuses[selCol].id}"]`);
    target?.scrollIntoView({ block: "nearest", inline: "nearest" });
  });
</script>

<TopBar mode="board" {title} username={user.username} />

<main>
  {#if view}
    {#if statuses.length === 0}
      <p class="empty">This board has no columns.</p>
    {/if}
    <div class="columns">
      {#each statuses as status, i (status.id)}
        <Column
          {status}
          cards={view.columns.get(status.id)!}
          current={i === selCol}
          selectedId={i === selCol ? selectedId : null}
          children={view.children}
          pending={view.pending}
          onselect={selectCard}
          ontoggle={() => {}}
        />
      {/each}
    </div>
  {/if}
  <p class="message" role="status">{message}</p>
</main>

{#if overlay === "help"}
  <HelpOverlay mode="board" onclose={() => (overlay = null)} />
{/if}

<style>
  main {
    display: flex;
    flex-direction: column;
    height: calc(100vh - 3.2rem);
    box-sizing: border-box;
    padding: 1rem 1rem 0;
  }
  .columns {
    flex: 1;
    min-height: 0;
    display: flex;
    gap: 1.75rem;
    align-items: flex-start;
    overflow-x: auto;
    padding: 4px 4px 0.5rem;
  }
  .empty {
    color: #555;
  }
  .message {
    min-height: 1.2em;
    margin: 0.3rem 0;
    color: #b00020;
  }
</style>
