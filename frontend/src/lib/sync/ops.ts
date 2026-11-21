// Ops (plan §3.2): builders, the confirmed state they apply to, optimistic application of
// pending ops, and undo inverses. Pure functions; the store (store.ts) owns the state.
//
// Unchanged cards keep their object identity through every rebuild, so a tile whose card
// didn't change is not re-rendered.

import type { Card, Status } from "../api/boards";
import { uuid7 } from "../ids";

/** A child pasted with its parent (`p` of a copied card). */
export interface ChildData {
  id: string;
  title: string;
  description?: string;
  tags?: string[];
  date?: string | null;
  is_done?: boolean;
}

export interface Neighbours {
  after_id?: string;
  before_id?: string;
}

/** A top-level card (`status_id`, with pasted `children`) or a child (`parent_id`; its
 * neighbours are siblings). Exactly one of the two is set. */
export interface CardCreateData extends ChildData, Neighbours {
  status_id?: string;
  parent_id?: string;
  children?: ChildData[];
}

/** The fields a card.update writes (only the keys present). Text fields are checked
 * against the op's base_seq on the server; is_done is last write wins. */
export interface CardFields {
  title?: string;
  description?: string;
  tags?: string[];
  date?: string | null;
  is_done?: boolean;
}

export type TextField = "title" | "description" | "tags" | "date";

interface OpBase {
  op_id: string;
  /** For an undo: the seq of the op being undone (the store fills it in when sending). */
  base_seq: number;
  undo?: boolean;
}

export type Op =
  | (OpBase & { kind: "card.create"; data: CardCreateData })
  | (OpBase & { kind: "card.update"; data: { id: string; fields: CardFields } })
  | (OpBase & { kind: "card.delete"; data: { id: string } })
  | (OpBase & { kind: "card.move"; data: { id: string; status_id: string } & Neighbours })
  | (OpBase & { kind: "card.restore"; data: { id: string } })
  | (OpBase & {
      kind: "status.create";
      data: { id: string; name: string; color: string } & Neighbours;
    })
  | (OpBase & { kind: "status.update"; data: { id: string; name?: string; color?: string } })
  | (OpBase & { kind: "status.move"; data: { id: string } & Neighbours })
  | (OpBase & { kind: "status.delete"; data: { id: string } });

export interface BoardEvent {
  seq: number;
  op_id: string;
  client_id: string;
  actor: { id: string; username: string };
  kind: Op["kind"];
  data: {
    card?: Card;
    /** pasted or restored children */
    children?: Card[];
    id?: string;
    deleted_ids?: string[];
    status?: Status;
    /** soft-deleted cards purged with a deleted column */
    purged_ids?: string[];
  };
}

/** Server state at `seq`. */
export interface Confirmed {
  seq: number;
  /** in column order */
  statuses: Status[];
  cards: Map<string, Card>;
}

export interface ChildCount {
  done: number;
  total: number;
}

/** What the board renders: confirmed with pending ops applied on top. */
export interface BoardView {
  seq: number;
  statuses: Status[];
  /** status id → top-level cards in column order */
  columns: Map<string, Card[]>;
  /** parent id → its live children (for the n/m badge) */
  children: Map<string, ChildCount>;
  /** parent id → its live children in order (the card view's checklist) */
  kids: Map<string, Card[]>;
  /** ids of cards with an unconfirmed create */
  pending: Set<string>;
}

// --- builders ------------------------------------------------------------------------

const base = (seq: number) => ({ op_id: uuid7(), base_seq: seq });

export function createCard(seq: number, data: Omit<CardCreateData, "id">, id = uuid7()): Op {
  return { ...base(seq), kind: "card.create", data: { id, ...data } };
}

export function setDone(seq: number, id: string, isDone: boolean): Op {
  return updateCard(seq, id, { is_done: isDone });
}

/** `baseSeq`: for text fields, the seq frozen when the field was entered (plan §3.2). */
export function updateCard(baseSeq: number, id: string, fields: CardFields): Op {
  return { ...base(baseSeq), kind: "card.update", data: { id, fields } };
}

/** `o` / `O` in card mode: a child next to a sibling (or at the end). */
export function createChild(
  seq: number,
  parentId: string,
  title: string,
  at: Neighbours = {},
  id = uuid7(),
): Op {
  return {
    ...base(seq),
    kind: "card.create",
    data: { id, parent_id: parentId, title, ...defined(at) },
  };
}

export function deleteCard(seq: number, id: string): Op {
  return { ...base(seq), kind: "card.delete", data: { id } };
}

export function moveCard(seq: number, id: string, statusId: string, at: Neighbours = {}): Op {
  return { ...base(seq), kind: "card.move", data: { id, status_id: statusId, ...defined(at) } };
}

export function restoreCard(seq: number, id: string): Op {
  return { ...base(seq), kind: "card.restore", data: { id } };
}

export function createStatus(
  seq: number,
  name: string,
  color: string,
  at: Neighbours = {},
  id = uuid7(),
): Op {
  return { ...base(seq), kind: "status.create", data: { id, name, color, ...defined(at) } };
}

export function updateStatus(seq: number, id: string, fields: { name?: string; color?: string }) {
  return { ...base(seq), kind: "status.update", data: { id, ...fields } } satisfies Op;
}

export function moveStatus(seq: number, id: string, at: Neighbours = {}): Op {
  return { ...base(seq), kind: "status.move", data: { id, ...defined(at) } };
}

export function deleteStatus(seq: number, id: string): Op {
  return { ...base(seq), kind: "status.delete", data: { id } };
}

/** Drops undefined neighbours, so the JSON only carries the ones that exist. */
function defined(at: Neighbours): Neighbours {
  return {
    ...(at.after_id && { after_id: at.after_id }),
    ...(at.before_id && { before_id: at.before_id }),
  };
}

/** The neighbours of `list[i]` (for putting it back where it was). */
function around(list: readonly { id: string }[], i: number): Neighbours {
  return defined({ after_id: list[i - 1]?.id, before_id: list[i + 1]?.id });
}

// --- undo ----------------------------------------------------------------------------

/** The op that undoes `op`, from the view just before `op` was applied; null if there is
 * nothing to undo. Sent with `undo: true`; the store sets `base_seq` to the seq `op` got. */
export function inverseOf(op: Op, view: BoardView): Op | null {
  const inv = inverseOp(op, view);
  return inv && { ...inv, undo: true };
}

function inverseOp(op: Op, view: BoardView): Op | null {
  switch (op.kind) {
    case "card.create":
      return deleteCard(0, op.data.id);
    case "card.update": {
      const old = cardById(view, op.data.id);
      if (!old) return null;
      const back: CardFields = {};
      for (const f of Object.keys(op.data.fields) as (keyof CardFields)[]) {
        (back as Record<string, unknown>)[f] = f === "tags" ? [...old.tags] : old[f];
      }
      return updateCard(0, op.data.id, back);
    }
    case "card.move": {
      const hit = findCard(view.columns, op.data.id);
      if (!hit) return null;
      const [col, i] = hit;
      return moveCard(0, op.data.id, col[i].status_id!, around(col, i));
    }
    case "card.delete":
      return restoreCard(0, op.data.id);
    case "card.restore":
      return deleteCard(0, op.data.id);
    case "status.create":
      return deleteStatus(0, op.data.id);
    case "status.update": {
      const s = view.statuses.find((x) => x.id === op.data.id);
      if (!s) return null;
      return updateStatus(0, s.id, {
        ...(op.data.name !== undefined && { name: s.name }),
        ...(op.data.color !== undefined && { color: s.color }),
      });
    }
    case "status.move": {
      const i = view.statuses.findIndex((x) => x.id === op.data.id);
      return i < 0 ? null : moveStatus(0, op.data.id, around(view.statuses, i));
    }
    case "status.delete": {
      const i = view.statuses.findIndex((x) => x.id === op.data.id);
      if (i < 0) return null;
      const s = view.statuses[i];
      return createStatus(0, s.name, s.color, around(view.statuses, i), s.id);
    }
  }
}

// --- confirmed state -----------------------------------------------------------------

// Keys are ASCII, so JS string order is the server's byte order (COLLATE "C").
const byPosition = (a: { id: string; position: string }, b: { id: string; position: string }) =>
  a.position < b.position ? -1 : a.position > b.position ? 1 : a.id < b.id ? -1 : 1;

export function confirmedFrom(seq: number, statuses: Status[], cards: Card[]): Confirmed {
  return {
    seq,
    statuses: [...statuses].sort(byPosition),
    cards: new Map(cards.map((c) => [c.id, c])),
  };
}

/** Applies a server event in place (caller guarantees seq order). */
export function applyEvent(state: Confirmed, ev: BoardEvent): void {
  const d = ev.data;
  if (d.card) state.cards.set(d.card.id, d.card);
  for (const c of d.children ?? []) state.cards.set(c.id, c);
  for (const id of [...(d.deleted_ids ?? []), ...(d.purged_ids ?? [])]) state.cards.delete(id);
  if (d.status) {
    const s = d.status;
    state.statuses = [...state.statuses.filter((x) => x.id !== s.id), s].sort(byPosition);
  }
  if (ev.kind === "status.delete") state.statuses = state.statuses.filter((x) => x.id !== d.id);
  state.seq = ev.seq;
}

// --- view ----------------------------------------------------------------------------

function placeholder(d: ChildData, place: { status_id?: string; parent_id?: string }): Card {
  return {
    id: d.id,
    number: 0,
    status_id: place.status_id ?? null,
    parent_card_id: place.parent_id ?? null,
    position: "",
    title: d.title,
    description: d.description ?? "",
    is_done: d.is_done ?? false,
    tags: d.tags ?? [],
    date: d.date ?? null,
    field_meta: {},
    created_at: "",
    updated_at: "",
  };
}

function findCard(columns: Map<string, Card[]>, id: string): [Card[], number] | null {
  for (const col of columns.values()) {
    const i = col.findIndex((c) => c.id === id);
    if (i >= 0) return [col, i];
  }
  return null;
}

/** A top-level card or a child, wherever it is in the view. */
function findAny(view: BoardView, id: string): [Card[], number] | null {
  return findCard(view.columns, id) ?? findCard(view.kids, id);
}

/** A live card (top-level or child) in the view. */
export function cardById(view: BoardView, id: string): Card | undefined {
  const hit = findAny(view, id);
  return hit ? hit[0][hit[1]] : undefined;
}

/** Inserts by the server's neighbour rule: after `after_id`, else before `before_id`, else
 * at the end. */
function insert<T extends { id: string }>(list: T[], item: T, at: Neighbours): void {
  let i = at.after_id ? list.findIndex((x) => x.id === at.after_id) : -1;
  if (i >= 0) i += 1;
  else {
    i = at.before_id ? list.findIndex((x) => x.id === at.before_id) : -1;
    if (i < 0) i = list.length;
  }
  list.splice(i, 0, item);
}

/** Applies one pending op to the view in place. Columns touched are already copies. */
export function applyOptimistic(view: BoardView, op: Op): void {
  switch (op.kind) {
    case "card.create": {
      const d = op.data;
      if (findAny(view, d.id)) return;
      if (d.parent_id) {
        // A child: only while its parent is on the board.
        if (!findCard(view.columns, d.parent_id)) return;
        const kids = view.kids.get(d.parent_id) ?? [];
        view.kids.set(d.parent_id, kids);
        insert(kids, placeholder(d, { parent_id: d.parent_id }), d);
        view.pending.add(d.id);
        return;
      }
      const col = d.status_id ? view.columns.get(d.status_id) : undefined;
      if (!col) return;
      insert(col, placeholder(d, { status_id: d.status_id }), d);
      view.pending.add(d.id);
      if (d.children?.length) {
        view.kids.set(
          d.id,
          d.children.map((c) => placeholder(c, { parent_id: d.id })),
        );
      }
      return;
    }
    case "card.update": {
      const hit = findAny(view, op.data.id);
      if (hit) hit[0][hit[1]] = { ...hit[0][hit[1]], ...op.data.fields };
      return;
    }
    case "card.delete": {
      const hit = findAny(view, op.data.id);
      if (hit) hit[0].splice(hit[1], 1);
      view.kids.delete(op.data.id);
      return;
    }
    case "card.move": {
      const d = op.data;
      const hit = findCard(view.columns, d.id);
      const target = view.columns.get(d.status_id);
      if (!hit || !target) return;
      const [moved] = hit[0].splice(hit[1], 1);
      insert(
        target,
        moved.status_id === d.status_id ? moved : { ...moved, status_id: d.status_id },
        d,
      );
      return;
    }
    case "card.restore":
      // The deleted card isn't in the view any more; it shows up with the ack.
      return;
    case "status.create": {
      const d = op.data;
      if (view.columns.has(d.id)) return;
      view.statuses = [...view.statuses];
      insert(view.statuses, { id: d.id, name: d.name, color: d.color, position: "" }, d);
      view.columns.set(d.id, []);
      return;
    }
    case "status.update": {
      const { id, ...fields } = op.data;
      view.statuses = view.statuses.map((s) => (s.id === id ? { ...s, ...fields } : s));
      return;
    }
    case "status.move": {
      const i = view.statuses.findIndex((s) => s.id === op.data.id);
      if (i < 0) return;
      view.statuses = [...view.statuses];
      const [moved] = view.statuses.splice(i, 1);
      insert(view.statuses, moved, op.data);
      return;
    }
    case "status.delete":
      view.statuses = view.statuses.filter((s) => s.id !== op.data.id);
      view.columns.delete(op.data.id);
      return;
  }
}

export function buildView(state: Confirmed, pending: readonly Op[]): BoardView {
  const columns = new Map<string, Card[]>(state.statuses.map((s) => [s.id, []]));
  const kids = new Map<string, Card[]>();
  for (const c of state.cards.values()) {
    if (c.parent_card_id) {
      const list = kids.get(c.parent_card_id);
      if (list) list.push(c);
      else kids.set(c.parent_card_id, [c]);
    } else if (c.status_id) {
      columns.get(c.status_id)?.push(c);
    }
  }
  for (const col of columns.values()) col.sort(byPosition);
  for (const list of kids.values()) list.sort(byPosition);
  const view: BoardView = {
    seq: state.seq,
    statuses: state.statuses,
    columns,
    children: new Map(),
    kids,
    pending: new Set(),
  };
  for (const op of pending) applyOptimistic(view, op);
  for (const [parent, list] of view.kids) {
    if (!list.length) continue;
    const done = list.filter((c) => c.is_done).length;
    view.children.set(parent, { done, total: list.length });
  }
  return view;
}

/** A card's live children in order (confirmed state). */
export function childrenOf(state: Confirmed, id: string): Card[] {
  return [...state.cards.values()].filter((c) => c.parent_card_id === id).sort(byPosition);
}
