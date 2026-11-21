<script lang="ts">
  // Dashboard per .local/drawing/main.png: a wrapping grid of board tiles, keyboard-first.
  import BoardTile from "../components/BoardTile.svelte";
  import Confirm from "../components/Confirm.svelte";
  import HelpOverlay from "../components/HelpOverlay.svelte";
  import Prompt from "../components/Prompt.svelte";
  import TopBar from "../components/TopBar.svelte";
  import { logout, type User } from "../lib/api/auth";
  import {
    createBoard,
    deleteBoard,
    listBoards,
    renameBoard,
    type BoardItem,
  } from "../lib/api/boards";
  import { ApiError } from "../lib/api/client";
  import { pushMode } from "../lib/keys/dispatch";
  import { columnsFromTops, moveInGrid, type Direction } from "../lib/keys/grid";
  import type { Action } from "../lib/keys/keymap";

  let {
    user,
    initialSelected,
    notice = "",
    onopen,
    onloggedout,
  }: {
    user: User;
    initialSelected?: string;
    /** Why we came back from a board, if it wasn't the user's choice. */
    notice?: string;
    onopen: (id: string) => void;
    /** Logged out by the user, or the session is gone (401). */
    onloggedout: () => void;
  } = $props();

  const TITLE_MAX = 120;

  type Overlay =
    | { kind: "help" }
    | { kind: "create" }
    | { kind: "rename"; board: BoardItem }
    | { kind: "delete"; board: BoardItem }
    | { kind: "logout" };

  let boards = $state<BoardItem[]>([]);
  let loaded = $state(false);
  // svelte-ignore state_referenced_locally (only the first value matters)
  let selectedId = $state<string | undefined>(initialSelected);
  let overlay = $state<Overlay | null>(null);
  // svelte-ignore state_referenced_locally (shown once, cleared by the next key)
  let message = $state(notice);
  let now = $state(Date.now());
  let grid: HTMLElement | undefined = $state();

  const selectedIndex = $derived(boards.findIndex((b) => b.id === selectedId));
  const selected = $derived(selectedIndex >= 0 ? boards[selectedIndex] : undefined);

  function fail(e: unknown): string {
    if (e instanceof ApiError && e.status === 401) {
      onloggedout();
      return "";
    }
    return e instanceof ApiError ? e.message : "Something went wrong";
  }

  async function load() {
    try {
      boards = await listBoards();
      if (!boards.some((b) => b.id === selectedId)) selectedId = boards[0]?.id;
    } catch (e) {
      message = fail(e);
    }
    loaded = true;
  }

  function columns(): number {
    const tiles = grid?.querySelectorAll<HTMLElement>("[data-tile]") ?? [];
    return columnsFromTops(Array.from(tiles, (t) => t.offsetTop));
  }

  function move(dir: Direction) {
    const i = moveInGrid(selectedIndex, dir, columns(), boards.length);
    if (i >= 0) selectedId = boards[i].id;
  }

  function onkey(action: Action) {
    message = "";
    switch (action) {
      case "left":
      case "down":
      case "up":
      case "right":
        return move(action);
      case "open":
        if (selected) onopen(selected.id);
        return;
      case "create":
        overlay = { kind: "create" };
        return;
      case "rename":
        if (selected) overlay = { kind: "rename", board: selected };
        return;
      case "delete":
        if (selected) overlay = { kind: "delete", board: selected };
        return;
      case "logout":
        overlay = { kind: "logout" };
        return;
      case "help":
        overlay = { kind: "help" };
        return;
    }
  }

  function checkTitle(raw: string): string | null {
    const title = raw.trim();
    return title ? null : "Title can't be empty";
  }

  async function submitCreate(raw: string): Promise<string | void> {
    const err = checkTitle(raw);
    if (err) return err;
    try {
      const board = await createBoard(raw.trim());
      boards.push(board);
      selectedId = board.id;
      overlay = null;
    } catch (e) {
      return fail(e);
    }
  }

  async function submitRename(id: string, raw: string): Promise<string | void> {
    const err = checkTitle(raw);
    if (err) return err;
    try {
      const updated = await renameBoard(id, raw.trim());
      boards = boards.map((b) => (b.id === id ? updated : b));
      overlay = null;
    } catch (e) {
      return fail(e);
    }
  }

  async function confirmDelete(board: BoardItem) {
    overlay = null;
    // Optimistic: the tile goes at once, so the next key already acts on its neighbour.
    const i = boards.findIndex((b) => b.id === board.id);
    if (i < 0) return;
    boards.splice(i, 1);
    if (selectedId === board.id) selectedId = boards[Math.min(i, boards.length - 1)]?.id;
    try {
      await deleteBoard(board.id);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) return; // already gone
      message = fail(e);
      boards.splice(Math.min(i, boards.length), 0, board);
    }
  }

  async function confirmLogout() {
    overlay = null;
    try {
      await logout();
    } catch (e) {
      message = fail(e);
      return;
    }
    onloggedout();
  }

  $effect(() => pushMode("dashboard", (a) => onkey(a)));

  $effect(() => {
    const t = setInterval(() => (now = Date.now()), 30_000);
    return () => clearInterval(t);
  });

  $effect(() => {
    if (!selectedId || !grid) return;
    grid.querySelector(`[data-tile="${selectedId}"]`)?.scrollIntoView({ block: "nearest" });
  });

  load();
</script>

<TopBar mode="dashboard" username={user.username} />

<main>
  {#if loaded && boards.length === 0}
    <p class="empty">No boards yet. Press <kbd>a</kbd> to create a board.</p>
  {/if}
  <div class="grid" role="listbox" aria-label="Boards" bind:this={grid}>
    {#each boards as board (board.id)}
      <BoardTile
        {board}
        {now}
        selected={board.id === selectedId}
        onselect={() => (selectedId = board.id)}
        onopen={() => onopen(board.id)}
      />
    {/each}
  </div>
  <p class="message" role="status">{message}</p>
</main>

{#if overlay?.kind === "help"}
  <HelpOverlay mode="dashboard" onclose={() => (overlay = null)} />
{:else if overlay?.kind === "create"}
  <Prompt
    label="New board title"
    maxlength={TITLE_MAX}
    onsubmit={submitCreate}
    oncancel={() => (overlay = null)}
  />
{:else if overlay?.kind === "rename"}
  {@const id = overlay.board.id}
  <Prompt
    label="Rename board"
    initial={overlay.board.title}
    maxlength={TITLE_MAX}
    onsubmit={(v) => submitRename(id, v)}
    oncancel={() => (overlay = null)}
  />
{:else if overlay?.kind === "delete"}
  {@const board = overlay.board}
  <Confirm
    message={`Delete board "${board.title}" and all its cards?`}
    onyes={() => confirmDelete(board)}
    onno={() => (overlay = null)}
  />
{:else if overlay?.kind === "logout"}
  <Confirm message="Log out?" onyes={confirmLogout} onno={() => (overlay = null)} />
{/if}

<style>
  main {
    padding: 1.25rem 1rem;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(18rem, 1fr));
    gap: 1.25rem;
  }
  .empty {
    color: #555;
  }
  .message {
    min-height: 1.2em;
    color: #b00020;
  }
  kbd {
    font: inherit;
    border: 1px solid #888;
    padding: 0 0.3rem;
  }
</style>
