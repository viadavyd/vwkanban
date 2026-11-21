<script module lang="ts">
  /** A card not created yet (`a`/`A` on the board): where it goes. */
  export interface NewCard {
    status_id: string;
    after_id?: string;
    before_id?: string;
  }
</script>

<script lang="ts">
  // CARD mode (plan §4.2–4.4): the card view, a centred overlay laid out like the notes'
  // ASCII card. A row cursor (j/k) runs over title → tags → due date → description →
  // child 1 … n → [add child]; `i`/`a` edit a row in a vim field (VimField, FIELD mode).
  //
  // Text is never lost (plan §3.4, §3.5):
  // - Leaving a field saves it (`card.update` with the base_seq frozen at field entry).
  //   A field that can't be saved (conflict, invalid, card deleted) keeps its draft on
  //   the row; `i` reopens it with the draft, `:w!` keeps mine, `:e!` takes theirs.
  // - Closing the card with drafts that weren't saved puts a snapshot of the card (with
  //   the drafts) in the register, so `p` on the board recreates it. Same for a child
  //   whose create came back `gone`.
  import { onDestroy, untrack } from "svelte";
  import type { Card } from "../lib/api/boards";
  import { tagColor } from "../lib/colors";
  import { FieldSession, parse, SINGLE_LINE, textOf } from "../lib/editor/session";
  import VimField from "../lib/editor/VimField.svelte";
  import type { VimMode } from "../lib/editor/vim";
  import { uuid7 } from "../lib/ids";
  import { pushMode } from "../lib/keys/dispatch";
  import type { Action, ExCommand } from "../lib/keys/keymap";
  import {
    cardById,
    createCard,
    createChild,
    deleteCard,
    setDone,
    updateCard,
    type BoardView,
    type CardFields,
    type Neighbours,
    type Op,
    type TextField,
  } from "../lib/sync/ops";
  import { snapshot, type Snapshot } from "../lib/sync/register";
  import { CLIENT_ID, type Answer, type BoardStore } from "../lib/sync/store";
  import HelpOverlay from "./HelpOverlay.svelte";

  let {
    store,
    view,
    cardId,
    newCard = null,
    deletedBy = null,
    onclose,
    oncreated,
    onregister,
    onmode,
  }: {
    store: BoardStore;
    view: BoardView;
    cardId: string;
    newCard?: NewCard | null;
    /** Who deleted the card while it was open (from the board's remote events). */
    deletedBy?: string | null;
    onclose: () => void;
    /** The new card's create was sent (the board selects it). */
    oncreated: (id: string) => void;
    /** A snapshot to keep in the register, and what to tell the user. */
    onregister: (snap: Snapshot, message: string) => void;
    /** The top bar's mode: CARD, or vim's mode in a field. */
    onmode: (label: string) => void;
  } = $props();

  type Row =
    | { kind: "field"; field: TextField }
    | { kind: "child"; id: string }
    | { kind: "newChild" }
    | { kind: "add" };

  const FIELDS: TextField[] = ["title", "tags", "date", "description"];
  const LABEL: Record<TextField, string> = {
    title: "Title",
    tags: "Tags",
    date: "Due date",
    description: "Description",
  };

  // svelte-ignore state_referenced_locally (the placeholder decides once, at open)
  let created = $state(newCard === null);
  let cursor = $state(0);
  let message = $state("");
  let help = $state(false);
  let closed = false;
  /** A child being added with o/O: its id, where it goes, and its row. */
  let adding = $state<{ id: string; at: Neighbours; index: number } | null>(null);
  /** The row being edited, its session and how vim starts. */
  let editing = $state<{ key: string; session: FieldSession; start: "normal" | "insert" } | null>(
    null,
  );
  /** Sessions whose draft isn't saved yet (unsaved, invalid, conflicting, in flight). */
  const drafts = new Map<string, FieldSession>();
  /** Bumped when a session (plain object) changes, to re-render. */
  let version = $state(0);
  /** Child ids seen in this view (for the card-scoped undo, even after a delete). */
  const touched = new Set<string>();
  let field: VimField | undefined = $state();

  const live = $derived(cardById(view, cardId));
  /** The card as last seen (it stays shown after a remote delete). */
  let lastSeen = $state.raw<Card | null>(null);
  $effect(() => {
    if (live) lastSeen = live;
  });
  const placeholder = $derived<Card>({
    id: cardId,
    number: 0,
    status_id: newCard?.status_id ?? null,
    parent_card_id: null,
    position: "",
    title: "",
    description: "",
    is_done: false,
    tags: [],
    date: null,
    field_meta: {},
    created_at: "",
    updated_at: "",
  });
  const card = $derived<Card>(live ?? lastSeen ?? placeholder);
  const gone = $derived(created && !live && !view.pending.has(cardId));
  const kids = $derived(view.kids.get(cardId) ?? []);
  let lastKids = $state.raw<Card[]>([]);
  $effect(() => {
    if (live) lastKids = kids;
    for (const k of kids) touched.add(k.id);
  });
  const shownKids = $derived(live ? kids : lastKids);

  const rows = $derived.by<Row[]>(() => {
    const list: Row[] = FIELDS.map((f) => ({ kind: "field", field: f }));
    const children: Row[] = shownKids.map((k) => ({ kind: "child", id: k.id }));
    if (adding) children.splice(adding.index, 0, { kind: "newChild" });
    return [...list, ...children, { kind: "add" }];
  });
  const row = $derived(rows[Math.min(cursor, rows.length - 1)]);
  const childOf = (id: string) => shownKids.find((k) => k.id === id);

  const keyOf = (r: Row) =>
    r.kind === "field" ? r.field : r.kind === "child" ? `child:${r.id}` : r.kind;

  // --- remote changes: flag, never touch the draft --------------------------------------

  $effect(() => {
    void view; // every new view
    const sessions = [...drafts.values(), ...(editing ? [editing.session] : [])];
    for (const s of sessions) {
      const c = cardById(view, s.cardId);
      if (c) s.observe(c);
    }
    untrack(() => (version += 1));
  });

  // --- saving ---------------------------------------------------------------------------

  function sessionFor(key: string, target: Card, f: TextField): FieldSession {
    return (
      drafts.get(key) ?? new FieldSession(target.id, f, textOf(target, f), store.seq, CLIENT_ID)
    );
  }

  /** Sends a session's save; the draft stays in `drafts` until acked. */
  function send(key: string, s: FieldSession, force = false) {
    if (gone) {
      drafts.set(key, s);
      return;
    }
    const save = s.save(store.seq, force);
    if (!save) {
      if (s.error || s.dirty || s.needsChoice) drafts.set(key, s);
      else drafts.delete(key);
      if (s.error) message = s.error;
      version += 1;
      return;
    }
    const sent = s.draft;
    drafts.set(key, s);
    void store.submit(updateCard(save.baseSeq, s.cardId, save.fields)).then((a) => {
      answered(key, s, sent, save.fields, a);
    });
    version += 1;
  }

  function answered(key: string, s: FieldSession, sent: string, fields: CardFields, a: Answer) {
    if (a.ok) {
      s.acked(sent, a.seq);
      if (!s.dirty && !s.needsChoice && editing?.session !== s) drafts.delete(key);
    } else if (a.code === "conflict") {
      s.rejected(a.message);
      if (a.current) s.observe(a.current);
    } else {
      s.error = a.message;
    }
    version += 1;
    if (!a.ok) {
      message = a.message;
      // The card was closed meanwhile: the draft goes to the register.
      if (closed)
        onregister(
          withFields(card, shownKids, fields),
          `${a.message}; your edit is in the register (p pastes it)`,
        );
    }
  }

  function leaveField(text: string) {
    const e = editing;
    if (!e) return;
    editing = null;
    onmode("card");
    const r = row;
    e.session.draft = text;
    if (r.kind === "newChild") return finishChild(text);
    if (!created) {
      // A new card: the first title save creates it (plan §4.2).
      const title = text.trim();
      if (!title) return;
      if (!newCard) return;
      const op = createCard(store.seq, { ...newCard, title }, cardId);
      created = true;
      void store.submit(op);
      oncreated(cardId);
      return;
    }
    send(e.key, e.session);
  }

  function finishChild(text: string) {
    const a = adding;
    adding = null;
    const title = text.trim();
    if (!a || !title) return;
    const op = createChild(store.seq, cardId, title, a.at, a.id);
    void store.submit(op).then((ans) => {
      if (!ans.ok && ans.code === "gone") {
        onregister(
          { title, description: "", tags: [], date: null, is_done: false, children: [] },
          `${ans.message}; the child "${title}" is in the register (p pastes it)`,
        );
      }
    });
  }

  function ex(command: ExCommand["name"], bang: boolean, text: string) {
    const e = editing;
    if (!e) return;
    e.session.draft = text;
    if (row.kind === "newChild" || !created) {
      message = "leave the field (Esc) to save a new card or child";
      return;
    }
    if (command === "write") return send(e.key, e.session, bang);
    // :e / :e!
    if (!bang && e.session.dirty) {
      message = "unsaved changes: :e! drops them";
      return;
    }
    const c = cardById(view, e.session.cardId);
    if (!c) return;
    field?.setText(e.session.takeTheirs(c, store.seq));
    drafts.delete(e.key);
    version += 1;
  }

  // --- the register on close ------------------------------------------------------------

  /** The card's content with `fields` applied. */
  function withFields(c: Card, children: readonly Card[], fields: CardFields): Snapshot {
    return { ...snapshot(c, children), ...fields } as Snapshot;
  }

  /** The card with every unsaved draft applied (an invalid one is kept as text). */
  function withDrafts(): Snapshot | null {
    const pending = [...drafts.entries()].filter(([, s]) => s.dirty || s.needsChoice || s.error);
    if (!pending.length) return null;
    const snap = snapshot(card, shownKids);
    const notes: string[] = [];
    for (const [key, s] of pending) {
      const p = parse(s.field, s.draft);
      if (key.startsWith("child:")) {
        const i = shownKids.findIndex((k) => `child:${k.id}` === key);
        const title = s.draft.trim();
        if (i >= 0 && p.ok) snap.children[i] = { ...snap.children[i], ...p.fields };
        else if (title)
          snap.children.push({ title, description: "", tags: [], date: null, is_done: false });
      } else if (p.ok) Object.assign(snap, p.fields);
      else notes.push(`[unsaved ${LABEL[s.field].toLowerCase()}: ${s.draft}]`);
    }
    if (notes.length) snap.description = [snap.description, ...notes].filter(Boolean).join("\n\n");
    return snap;
  }

  function close() {
    if (closed) return;
    closed = true;
    popCard(); // at once: a key right after this one is the board's
    const snap = created ? withDrafts() : null;
    if (snap) {
      const why = gone
        ? `#${card.number} was deleted${deletedBy ? ` by ${deletedBy}` : ""}`
        : `#${card.number} has unsaved changes`;
      onregister(snap, `${why}; your card is in the register (p pastes it)`);
    }
    onclose();
  }

  // --- card mode keys -------------------------------------------------------------------

  function edit(start: "normal" | "insert") {
    const r = row;
    if (r.kind === "add") return addChild(shownKids.length, { after_id: shownKids.at(-1)?.id });
    if (!created && !(r.kind === "field" && r.field === "title")) return;
    if (r.kind === "field") {
      const key = r.field;
      editing = { key, session: sessionFor(key, card, r.field), start };
    } else if (r.kind === "child") {
      const kid = childOf(r.id);
      if (!kid) return;
      const key = `child:${kid.id}`;
      editing = { key, session: sessionFor(key, kid, "title"), start };
    }
  }

  function addChild(index: number, at: Neighbours) {
    if (!created) return void (message = "give the card a title first");
    if (gone) return void (message = "this card was deleted");
    const id = uuid7();
    adding = { id, at, index };
    cursor = FIELDS.length + index;
    editing = {
      key: "newChild",
      session: new FieldSession(id, "title", "", store.seq, CLIENT_ID),
      start: "insert",
    };
  }

  /** o / O: a child below / above the row (on the rows above the children: the top). */
  function open(below: boolean) {
    const r = row;
    if (r.kind === "child") {
      const i = shownKids.findIndex((k) => k.id === r.id);
      return below ? addChild(i + 1, { after_id: r.id }) : addChild(i, { before_id: r.id });
    }
    if (r.kind === "add") return addChild(shownKids.length, { after_id: shownKids.at(-1)?.id });
    addChild(0, shownKids[0] ? { before_id: shownKids[0].id } : {});
  }

  function toggle() {
    if (!created || gone) return;
    const r = row;
    const target =
      r.kind === "child"
        ? childOf(r.id)
        : r.kind === "field" && r.field === "title"
          ? live
          : undefined;
    if (target) void store.submit(setDone(store.seq, target.id, !target.is_done));
  }

  function remove() {
    const r = row;
    if (r.kind !== "child" || gone) return;
    void store.submit(deleteCard(store.seq, r.id));
  }

  function undo() {
    const mine = (op: Op) =>
      "id" in op.data &&
      (op.data.id === cardId ||
        touched.has(op.data.id) ||
        ("parent_id" in op.data && op.data.parent_id === cardId));
    if (!store.undo(mine)) message = "nothing to undo on this card";
  }

  function onkey(action: Action) {
    message = "";
    const last = rows.length - 1;
    switch (action) {
      case "down":
        if (created) cursor = Math.min(cursor + 1, last);
        return;
      case "up":
        cursor = Math.max(cursor - 1, 0);
        return;
      case "edit":
        return edit("normal");
      case "append":
        return edit("insert");
      case "openBelow":
        return open(true);
      case "openAbove":
        return open(false);
      case "toggleDone":
        return toggle();
      case "delete":
        return remove();
      case "undo":
        return undo();
      case "help":
        help = true;
        return;
      case "back":
        return close();
    }
  }

  // Pushed while initialising (not in an effect): a VimField child pushes `field` during
  // its own init, which runs after ours, so `field` always sits on top of `card`.
  const popCard = pushMode("card", (a) => onkey(a));
  onDestroy(popCard);

  // A new card opens straight into its title, in INSERT (plan §4.2).
  untrack(() => {
    if (!created) {
      editing = {
        key: "title",
        session: new FieldSession(cardId, "title", "", 0, CLIENT_ID),
        start: "insert",
      };
    }
    onmode(editing ? "insert" : "card");
  });

  // --- rendering helpers ----------------------------------------------------------------

  function draftOf(key: string): FieldSession | undefined {
    void version;
    return drafts.get(key);
  }

  function choice(s: FieldSession | undefined): string {
    void version;
    if (!s) return "";
    if (s.needsChoice) return `${s.conflict ?? "remote changed"} — :w! keep mine · :e! take theirs`;
    if (s.error) return s.error;
    if (s.dirty) return "unsaved";
    return "";
  }

  const vimMode = (m: VimMode) => onmode(m);
</script>

{#snippet editor(key: string, f: TextField, label: string)}
  {#if editing && editing.key === key}
    <VimField
      bind:this={field}
      text={editing.session.draft}
      singleLine={SINGLE_LINE.has(f)}
      {label}
      start={editing.start}
      onleave={leaveField}
      onex={ex}
      onmode={vimMode}
      ondraft={(t) => editing && (editing.session.draft = t)}
    />
    {@const c = choice(editing.session)}
    {#if c && c !== "unsaved"}<p class="choice" data-testid="choice">{c}</p>{/if}
  {/if}
{/snippet}

<div class="backdrop">
  <div
    class="card"
    role="dialog"
    aria-modal="true"
    aria-label={created ? `Card #${card.number || "…"}` : "New card"}
    data-testid="card-view"
  >
    {#if gone}
      <p class="banner" role="alert" data-testid="deleted-banner">
        #{card.number} deleted{deletedBy ? ` by ${deletedBy}` : ""} — your edits stay here and go to the
        register when you close the card
      </p>
    {/if}
    {#each rows as r, i (keyOf(r))}
      {@const key = keyOf(r)}
      {@const at = i === Math.min(cursor, rows.length - 1)}
      {@const d = draftOf(key)}
      <div
        class="row {r.kind}"
        class:at
        class:disabled={!created && i > 0}
        data-row={key}
        aria-current={at ? "true" : undefined}
      >
        {#if r.kind === "field"}
          {#if editing?.key === key}
            {@render editor(key, r.field, LABEL[r.field])}
          {:else}
            {@const text = d ? d.draft : textOf(card, r.field)}
            {#if r.field === "title"}
              <span class="head">
                <span class="num">#{created ? card.number || "…" : "new"}</span>
                <span class="box" aria-label={card.is_done ? "done" : "not done"}>
                  {card.is_done ? "☑" : "☐"}
                </span>
                <span class="title" class:done={card.is_done} data-testid="card-title">
                  {text || "(untitled)"}
                </span>
              </span>
            {:else if r.field === "tags"}
              <span class="label">tags</span>
              {#if d}
                <span data-testid="card-tags">{text || "—"}</span>
              {:else if card.tags.length}
                <span class="tags" data-testid="card-tags">
                  {#each card.tags as t (t)}<span class="tag" style:background={tagColor(t)}>
                      {t}
                    </span>{/each}
                </span>
              {:else}<span class="empty" data-testid="card-tags">no tags</span>{/if}
            {:else if r.field === "date"}
              <span class="label">due</span>
              <span class:empty={!text} data-testid="card-date">{text || "no due date"}</span>
            {:else}
              <div class="description" class:empty={!text} data-testid="card-description">
                {text || "(no description)"}
              </div>
            {/if}
            {@const c = choice(d)}
            {#if c}<p class="choice" data-testid="choice">{c}</p>{/if}
          {/if}
        {:else if r.kind === "child"}
          {@const kid = childOf(r.id)}
          {#if kid}
            <span class="box" aria-label={kid.is_done ? "done" : "not done"}>
              {kid.is_done ? "☑" : "☐"}
            </span>
            {#if editing?.key === key}
              <div class="grow">{@render editor(key, "title", "Child title")}</div>
            {:else}
              <span class="child-title" class:done={kid.is_done} data-testid="child-title">
                {d ? d.draft : kid.title}
              </span>
              {@const c = choice(d)}
              {#if c}<p class="choice" data-testid="choice">{c}</p>{/if}
            {/if}
          {/if}
        {:else if r.kind === "newChild"}
          <span class="box">☐</span>
          <div class="grow">{@render editor("newChild", "title", "New child")}</div>
        {:else}
          <span class="add">[add child]</span>
        {/if}
      </div>
      {#if i === 0 || (r.kind === "field" && r.field === "description")}<hr />{/if}
    {/each}
    <p class="message" role="status" data-testid="card-message">{message}</p>
  </div>
</div>

{#if help}
  <HelpOverlay mode="card" onclose={() => (help = false)} />
{/if}

<style>
  .backdrop {
    position: fixed;
    inset: 0;
    background: rgb(0 0 0 / 0.25);
    display: grid;
    place-items: center;
    padding: 1rem;
  }
  .card {
    width: min(40rem, 100%);
    max-height: calc(100vh - 2rem);
    overflow: auto;
    background: #fff;
    border: 3px double #222;
    padding: 0.75rem 1rem;
    box-sizing: border-box;
  }
  .banner {
    margin: 0 0 0.5rem;
    padding: 0.3rem 0.5rem;
    background: #fde7e9;
    color: #8a0012;
  }
  .row {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    align-items: baseline;
    padding: 0.25rem 0.4rem;
    border-left: 3px solid transparent;
  }
  .row.at {
    border-left-color: #222;
    background: #f2f2f2;
  }
  .row.disabled {
    opacity: 0.45;
  }
  .row > :global(.field),
  .grow {
    flex: 1 1 100%;
  }
  .row.child .grow,
  .row.newChild .grow {
    flex: 1;
  }
  .head {
    display: flex;
    gap: 0.5rem;
    font-weight: 600;
  }
  .num {
    color: #555;
  }
  .done {
    color: #777;
    text-decoration: line-through;
  }
  .label {
    color: #555;
    min-width: 2.5rem;
  }
  .tags {
    display: flex;
    flex-wrap: wrap;
    gap: 0.3rem;
  }
  .tag {
    padding: 0 0.4rem;
    border-radius: 0.6rem;
    font-size: 0.85em;
  }
  .description {
    white-space: pre-wrap;
    flex: 1 1 100%;
    min-height: 3em;
  }
  .empty {
    color: #888;
  }
  .add {
    color: #555;
  }
  .choice {
    flex: 1 1 100%;
    margin: 0.2rem 0 0;
    color: #8a4b00;
    font-size: 0.9em;
  }
  hr {
    border: none;
    border-top: 1px dashed #999;
    margin: 0.3rem 0;
  }
  .message {
    min-height: 1.2em;
    margin: 0.4rem 0 0;
    color: #b00020;
  }
</style>
