<script module lang="ts">
  import type { Register } from "../lib/sync/register";

  // One unnamed register per tab (plan §4.3). A copy outlives the board it came from (it
  // pastes as new cards anywhere); a move mark is cleared when you leave the board.
  let register = $state<Register>(null);
</script>

<script lang="ts">
  // Board view per .local/drawing/board.png and plan §4.4: columns of card tiles,
  // keyboard-first (keys in keymap.ts, board mode and its `s` prefix, column mode).
  import CardView, { type NewCard } from "../components/CardView.svelte";
  import Column from "../components/Column.svelte";
  import Confirm from "../components/Confirm.svelte";
  import HelpOverlay from "../components/HelpOverlay.svelte";
  import MembersOverlay from "../components/MembersOverlay.svelte";
  import Prompt from "../components/Prompt.svelte";
  import TopBar from "../components/TopBar.svelte";
  import type { User } from "../lib/api/auth";
  import {
    CSV_MAX_BYTES,
    exportUrl,
    getBoard,
    importCsv,
    type BoardDetail,
    type ImportResult,
    type Status,
  } from "../lib/api/boards";
  import { ApiError } from "../lib/api/client";
  import { loadEditor } from "../lib/editor/load";
  import { uuid7 } from "../lib/ids";
  import { COLOR_NAMES, nextColor } from "../lib/colors";
  import {
    clampRow,
    COLUMN_NAME_MAX,
    columnMove,
    columnNameError,
    moveCursor,
    rowAfterDelete,
  } from "../lib/keys/board";
  import { pushMode } from "../lib/keys/dispatch";
  import type { Action } from "../lib/keys/keymap";
  import {
    createStatus,
    deleteCard,
    deleteStatus,
    moveCard,
    moveStatus,
    setDone,
    updateStatus,
    type BoardEvent,
    type BoardView,
    type Op,
  } from "../lib/sync/ops";
  import { pasteOp, snapshot, type Snapshot } from "../lib/sync/register";
  import {
    BoardSocket,
    boardSocketUrl,
    type PresenceUser,
    type SyncStatus,
  } from "../lib/sync/socket";
  import { BoardStore, CLIENT_ID } from "../lib/sync/store";

  let {
    id,
    user,
    onback,
    onloggedout,
  }: {
    id: string;
    user: User;
    /** Back to the dashboard; `why` is shown there when the board closed on its own. */
    onback: (why?: string) => void;
    onloggedout: () => void;
  } = $props();

  type Overlay =
    | { kind: "help" }
    | { kind: "members" }
    | { kind: "columnCreate" }
    | { kind: "columnRename"; status: Status }
    | { kind: "columnDelete"; status: Status }
    | { kind: "import"; file: File; preview: ImportResult };

  let title = $state("…");
  let store = $state.raw<BoardStore | null>(null);
  let socket: BoardSocket | null = null;
  let syncStatus = $state<SyncStatus>("connecting");
  let unsaved = $state(0);
  let presence = $state<PresenceUser[]>([]);
  const others = $derived(presence.filter((u) => u.user_id !== user.id));
  // Raw: the view is rebuilt as a whole; unchanged cards keep their identity.
  let view = $state.raw<BoardView | null>(null);
  let overlay = $state<Overlay | null>(null);
  // `s` was pressed: the next key is a column command (column mode).
  let prefix = $state(false);
  // The card open in card mode (i, or a/A for a new one), and who deleted it meanwhile.
  let opened = $state<{ id: string; newCard: NewCard | null; row: number } | null>(null);
  let openDeletedBy = $state<string | null>(null);
  // The top bar's mode: BOARD, CARD, or vim's NORMAL / INSERT / VISUAL in a field.
  let modeLabel = $state("board");
  let message = $state("");
  // The message is news, not an error (e.g. "imported 12 cards").
  let messageOk = $state(false);
  // `I`: the hidden file picker, and an upload on its way (one at a time).
  let fileInput = $state<HTMLInputElement>();
  let importing = $state(false);

  // Selection: a column and a card in it (by id, so it survives inserts above it).
  // `want` is the row h/l try to keep.
  let selCol = $state(0);
  let selId = $state<string | null>(null);
  let want = $state(0);

  const statuses = $derived(view?.statuses ?? []);
  const current = $derived<Status | undefined>(statuses[selCol]);
  const colCards = $derived(view && current ? (view.columns.get(current.id) ?? []) : []);
  // The selected row; if the card went away (e.g. a resync), fall back to the kept row.
  const selRow = $derived.by(() => {
    const i = selId ? colCards.findIndex((c) => c.id === selId) : -1;
    return i >= 0 ? i : clampRow(want, colCards.length);
  });
  const selectedId = $derived(selRow >= 0 ? (colCards[selRow]?.id ?? null) : null);
  const marked = $derived(register?.kind === "move" ? register : null);
  // Top bar: what's pending in board mode (plan §4.4).
  // The number comes from the view: a card marked before its create is acked gets it then.
  const markedNumber = $derived.by(() => {
    if (!marked || !view) return 0;
    for (const col of view.columns.values()) {
      const c = col.find((x) => x.id === marked.id);
      if (c) return c.number;
    }
    return 0;
  });
  const pending = $derived(prefix ? "s…" : marked ? `x: #${markedNumber || "…"}` : "");

  function fail(e: unknown) {
    if (e instanceof ApiError && e.status === 401) onloggedout();
    else if (e instanceof ApiError && (e.status === 404 || e.status === 422)) {
      onback("that board doesn't exist or isn't shared with you");
    } else message = e instanceof ApiError ? e.message : "Something went wrong";
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
      onchange: (v) => {
        view = v;
        unsaved = store?.pendingCount ?? 0;
      },
      onmessage: (m) => (message = m),
      onloggedout,
      ongone: (why) => onback(why),
      onstatus: (s) => (syncStatus = s),
      onpresence: (users) => (presence = users),
      onremote: remoteChange,
      onreject: rejected,
      load: () => getBoard(boardId),
      connect: (hooks) => (socket = new BoardSocket(boardSocketUrl(boardId, location), hooks)),
    });
    view = store.view;
  }

  /** A teammate's change touched what we hold: clear a mark on a card they deleted, and
   * say so when they moved the selected card (plan §3.5, §9). */
  function remoteChange(ev: BoardEvent) {
    const who = ev.actor.username;
    if (ev.kind === "board.import") {
      note(`${who} imported ${cardCount(ev.data.created ?? 0)}`);
      return;
    }
    if (opened && ev.data.deleted_ids?.includes(opened.id)) openDeletedBy = who;
    if (marked && ev.data.deleted_ids?.includes(marked.id)) {
      message = `#${markedNumber} was deleted by ${who}`;
      register = null;
    } else if (ev.kind === "card.move" && ev.data.card?.id === selectedId) {
      message = `#${ev.data.card.number} was moved by ${who}`;
      selectCard(ev.data.card.id);
    }
  }

  /** A move of the x-marked card that the server refused: the mark is stale. */
  function rejected(op: Op, code: string) {
    if (code === "gone" && marked && "id" in op.data && op.data.id === marked.id) register = null;
  }

  function cardsOf(col: number) {
    return view?.columns.get(statuses[col]?.id) ?? [];
  }

  function select(col: number, row: number) {
    selCol = col;
    const cards = cardsOf(col);
    selId = row >= 0 ? (cards[row]?.id ?? null) : null;
  }

  function move(dir: "left" | "down" | "up" | "right") {
    if (!view) return;
    const lengths = statuses.map((_, i) => cardsOf(i).length);
    const next = moveCursor(lengths, { col: selCol, row: selRow }, dir, want);
    if (dir === "up" || dir === "down") want = Math.max(next.row, 0);
    select(next.col, next.row);
  }

  /** Selects a card wherever it is; false if it isn't on the board. */
  function selectCard(cardId: string): boolean {
    if (!view) return false;
    const col = statuses.findIndex((_, i) => cardsOf(i).some((c) => c.id === cardId));
    if (col < 0) return false;
    selCol = col;
    selId = cardId;
    want = cardsOf(col).findIndex((c) => c.id === cardId);
    return true;
  }

  function selectColumn(statusId: string) {
    const i = statuses.findIndex((s) => s.id === statusId);
    if (i >= 0) selCol = i;
  }

  /** Card mode on the selected card (`i`, double-click). The editor chunk starts loading
   * now: the first card open is what fetches it (plan §7). */
  function openCard(cardId: string | null = selectedId) {
    if (!cardId || !store) return;
    void loadEditor();
    openDeletedBy = null;
    opened = { id: cardId, newCard: null, row: selRow };
  }

  /** `a` / `A`: a new card below / above the selection, opened in card mode with its
   * title in INSERT. It is created when the title is first saved (plan §4.2). */
  function openNew(above: boolean) {
    if (!current || !store) return;
    void loadEditor();
    const newCard: NewCard = { status_id: current.id };
    let row = 0;
    if (selectedId && above) [newCard.before_id, row] = [selectedId, selRow];
    else if (selectedId) [newCard.after_id, row] = [selectedId, selRow + 1];
    openDeletedBy = null;
    opened = { id: uuid7(), newCard, row };
  }

  function created(cardId: string) {
    if (!opened) return;
    want = opened.row;
    if (!selectCard(cardId)) selId = cardId;
  }

  function closeCard() {
    const id = opened?.id;
    opened = null;
    modeLabel = "board";
    if (id) selectCard(id);
  }

  function keep(snap: Snapshot, why: string) {
    register = { kind: "copy", snapshot: snap };
    message = why;
  }

  function toggle(cardId: string) {
    const card = cardsOf(selCol).find((c) => c.id === cardId);
    if (card && store) store.submit(setDone(store.seq, card.id, !card.is_done));
  }

  function copySelected(): boolean {
    const card = colCards[selRow];
    if (!card || !store) return false;
    register = { kind: "copy", snapshot: snapshot(card, store.childrenOf(card.id)) };
    return true;
  }

  function remove() {
    if (!selectedId || !store) return;
    copySelected(); // d = delete and copy (notes.md): `p` pastes it back as a copy
    const row = rowAfterDelete(selRow, colCards.length);
    store.submit(deleteCard(store.seq, selectedId));
    want = Math.max(row, 0);
    select(selCol, row);
  }

  function mark() {
    const card = colCards[selRow];
    if (card) register = { kind: "move", id: card.id };
  }

  function paste() {
    if (!store || !current) return;
    const after = selectedId ? { after_id: selectedId } : {};
    if (!register) {
      message = "nothing to paste: y copies, x marks a card to move";
    } else if (register.kind === "copy") {
      const op = pasteOp(store.seq, register.snapshot, current.id, selectedId ?? undefined);
      store.submit(op);
      selectCard(op.data.id);
    } else {
      const { id: cardId } = register;
      register = null; // the move register is consumed
      if (cardId === selectedId) return; // pasted onto itself: nothing moves
      store.submit(moveCard(store.seq, cardId, current.id, after));
      selectCard(cardId);
    }
  }

  function undo() {
    const inv = store?.undo();
    if (!inv) {
      message = "nothing to undo";
      return;
    }
    if (inv.kind.startsWith("card.")) selectCard(inv.data.id);
    else selectColumn(inv.data.id);
  }

  function moveColumn(dir: "left" | "right") {
    if (!store || !current) return;
    const to = columnMove(
      statuses.map((s) => s.id),
      selCol,
      dir,
    );
    if (!to) return;
    const { to: col, ...at } = to;
    store.submit(moveStatus(store.seq, current.id, at));
    selCol = col; // the selected card moves with its column
  }

  async function createColumn(name: string): Promise<string | void> {
    const err = columnNameError(name, statuses);
    if (err) return err;
    if (!store) return;
    const color = COLOR_NAMES[statuses.length % COLOR_NAMES.length];
    const op = createStatus(store.seq, name.trim(), color, current ? { after_id: current.id } : {});
    overlay = null;
    store.submit(op);
    selectColumn(op.data.id);
    selId = null;
  }

  async function renameColumn(status: Status, name: string): Promise<string | void> {
    const err = columnNameError(name, statuses, status.id);
    if (err) return err;
    overlay = null;
    if (store && name.trim() !== status.name)
      store.submit(updateStatus(store.seq, status.id, { name: name.trim() }));
  }

  function columnCommand(action: Action) {
    prefix = false;
    if (!store) return;
    if (action === "create") {
      overlay = { kind: "columnCreate" };
      return;
    }
    if (!current) return;
    switch (action) {
      case "rename":
        overlay = { kind: "columnRename", status: current };
        return;
      case "cycleColor":
        store.submit(updateStatus(store.seq, current.id, { color: nextColor(current.color) }));
        return;
      case "delete":
        if (colCards.length) message = `column "${current.name}" is not empty`;
        else overlay = { kind: "columnDelete", status: current };
        return;
    }
  }

  function confirmDeleteColumn(status: Status) {
    overlay = null;
    if (!store) return;
    store.submit(deleteStatus(store.seq, status.id));
    selCol = Math.max(0, Math.min(selCol, statuses.length - 1));
  }

  function note(text: string) {
    message = text;
    messageOk = true;
  }

  const cardCount = (n: number) => `${n} card${n === 1 ? "" : "s"}`;

  // --- CSV (plan §3.6, §4.3) ---------------------------------------------------------

  /** `E`: the browser downloads the export (the server names the file). */
  function exportCsv() {
    const a = document.createElement("a");
    a.href = exportUrl(id);
    a.download = "";
    a.click();
  }

  /** `I`: opens the file picker from the keydown (a user gesture, so browsers allow it). */
  function pickCsv() {
    if (!store || !fileInput || importing) return;
    fileInput.value = "";
    fileInput.click();
  }

  /** A file was picked: a dry run shows what the import adds, then `y` imports. */
  async function picked() {
    const file = fileInput?.files?.[0];
    if (!file || !store) return;
    if (file.size > CSV_MAX_BYTES) {
      message = "file is larger than 5 MB";
      return;
    }
    importing = true;
    try {
      const preview = await importCsv(id, file, CLIENT_ID, true);
      if (!preview.created) note("the file has no cards to import");
      else if (opened || overlay) message = "import cancelled: close the open view first";
      else overlay = { kind: "import", file, preview };
    } catch (e) {
      importFailed(e);
    } finally {
      importing = false;
    }
  }

  function previewText(p: ImportResult) {
    const numbers = p.numbers === "kept" ? "keeping their numbers" : "with new numbers";
    return `Import ${cardCount(p.created)} into "${title}", ${numbers}?`;
  }

  function previewDetails(p: ImportResult) {
    const lines = [];
    if (p.statuses_created.length) lines.push(`new columns: ${p.statuses_created.join(", ")}`);
    return [...lines, ...p.warnings];
  }

  async function confirmImport(file: File) {
    overlay = null;
    importing = true;
    try {
      const r = await importCsv(id, file, CLIENT_ID, false);
      note(`imported ${cardCount(r.created)}`);
      // The board.import event makes the store reload the board (plan §3.2).
    } catch (e) {
      importFailed(e);
    } finally {
      importing = false;
    }
  }

  function importFailed(e: unknown) {
    if (e instanceof ApiError && e.status === 401) onloggedout();
    else if (e instanceof ApiError && e.status === 404) {
      onback("that board doesn't exist or isn't shared with you");
    } else message = e instanceof ApiError ? e.message : "Something went wrong";
  }

  function onkey(action: Action) {
    message = "";
    messageOk = false;
    switch (action) {
      case "left":
      case "down":
      case "up":
      case "right":
        return move(action);
      case "open":
        return openCard();
      case "create":
        return openNew(false);
      case "createAbove":
        return openNew(true);
      case "toggleDone":
        if (selectedId) toggle(selectedId);
        return;
      case "delete":
        return remove();
      case "copy":
        copySelected();
        return;
      case "mark":
        return mark();
      case "paste":
        return paste();
      case "undo":
        return undo();
      case "columnPrefix":
        prefix = true;
        return;
      case "columnLeft":
      case "columnRight":
        return moveColumn(action === "columnLeft" ? "left" : "right");
      case "back":
        // One level: clear what's pending first (plan §4.2), else to the dashboard.
        if (marked) register = null;
        else onback();
        return;
      case "help":
        overlay = { kind: "help" };
        return;
      case "members":
        overlay = { kind: "members" };
        return;
      case "exportCsv":
        return exportCsv();
      case "importCsv":
        return pickCsv();
    }
  }

  $effect(() => {
    load(id);
    return () => {
      store?.close();
      if (register?.kind === "move") register = null;
    };
  });

  $effect(() => pushMode("board", (a) => onkey(a)));

  // Reconnect at once when the network returns; show offline when it goes.
  $effect(() => {
    const online = () => socket?.retryNow();
    const offline = () => socket?.wentOffline();
    window.addEventListener("online", online);
    window.addEventListener("offline", offline);
    return () => {
      window.removeEventListener("online", online);
      window.removeEventListener("offline", offline);
    };
  });

  $effect(() => {
    if (!prefix) return;
    return pushMode("column", (a) => (a === "back" ? (prefix = false) : columnCommand(a)));
  });

  // Keep the selection in view (columns scroll on their own; the board scrolls sideways).
  $effect(() => {
    const target = selectedId
      ? document.querySelector(`[data-card="${selectedId}"]`)
      : current && document.querySelector(`[data-column="${current.id}"]`);
    target?.scrollIntoView({ block: "nearest", inline: "nearest" });
  });
</script>

<TopBar
  mode={modeLabel}
  {pending}
  {title}
  username={user.username}
  {others}
  sync={{ status: syncStatus, pending: unsaved }}
/>

<main>
  {#if view}
    {#if statuses.length === 0}
      <p class="empty">This board has no columns. Press <kbd>s</kbd> <kbd>a</kbd> to add one.</p>
    {/if}
    <div class="columns">
      {#each statuses as status, i (status.id)}
        <Column
          {status}
          cards={view.columns.get(status.id) ?? []}
          current={i === selCol}
          selectedId={i === selCol ? selectedId : null}
          markedId={marked?.id ?? null}
          children={view.children}
          pending={view.pending}
          onselect={selectCard}
          ontoggle={(cardId) => {
            selectCard(cardId);
            toggle(cardId);
          }}
          onopen={(cardId) => {
            if (opened || overlay) return;
            selectCard(cardId);
            openCard(cardId);
          }}
        />
      {/each}
    </div>
  {/if}
  <p class="message" class:ok={messageOk} role="status">{message}</p>
  <!-- `I`: hidden, so it never holds focus (keys would go to it, not the board) -->
  <input
    bind:this={fileInput}
    type="file"
    accept=".csv,text/csv"
    hidden
    data-testid="csv-file"
    onchange={picked}
  />
</main>

{#if opened && store && view}
  {#key opened.id}
    <CardView
      {store}
      {view}
      cardId={opened.id}
      newCard={opened.newCard}
      deletedBy={openDeletedBy}
      onclose={closeCard}
      oncreated={created}
      onregister={keep}
      onmode={(m) => (modeLabel = m)}
    />
  {/key}
{/if}

{#if overlay?.kind === "help"}
  <HelpOverlay mode="board" onclose={() => (overlay = null)} />
{:else if overlay?.kind === "members"}
  <MembersOverlay boardId={id} {user} onclose={() => (overlay = null)} {onloggedout} />
{:else if overlay?.kind === "columnCreate"}
  <Prompt
    label="New column name"
    maxlength={COLUMN_NAME_MAX}
    onsubmit={createColumn}
    oncancel={() => (overlay = null)}
  />
{:else if overlay?.kind === "columnRename"}
  {@const status = overlay.status}
  <Prompt
    label="Rename column"
    initial={status.name}
    maxlength={COLUMN_NAME_MAX}
    onsubmit={(v) => renameColumn(status, v)}
    oncancel={() => (overlay = null)}
  />
{:else if overlay?.kind === "columnDelete"}
  {@const status = overlay.status}
  <Confirm
    message={`Delete column "${status.name}"?`}
    onyes={() => confirmDeleteColumn(status)}
    onno={() => (overlay = null)}
  />
{:else if overlay?.kind === "import"}
  {@const { file, preview } = overlay}
  <Confirm
    message={previewText(preview)}
    details={previewDetails(preview)}
    onyes={() => confirmImport(file)}
    onno={() => (overlay = null)}
  />
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
  kbd {
    font: inherit;
    border: 1px solid #888;
    padding: 0 0.3rem;
  }
  .message {
    min-height: 1.2em;
    margin: 0.3rem 0;
    color: #b00020;
  }
  .message.ok {
    color: #1b5e20;
  }
</style>
