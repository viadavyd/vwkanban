// Ops (plan §3.2): builders, the confirmed state they apply to, optimistic application of
// pending ops, and undo inverses. Pure functions; the store (store.ts) owns the state.
//
// Unchanged cards keep their object identity through every rebuild, so a tile whose card
// didn't change is not re-rendered.

import type { Card, Status } from "../api/boards";
import { uuid7 } from "../ids";

export interface CardCreateData {
  id: string;
  status_id: string;
  after_id?: string;
  before_id?: string;
  title: string;
}

interface OpBase {
  op_id: string;
  base_seq: number;
}

export type Op =
  | (OpBase & { kind: "card.create"; data: CardCreateData })
  | (OpBase & { kind: "card.update"; data: { id: string; fields: { is_done: boolean } } })
  | (OpBase & { kind: "card.delete"; data: { id: string } });

export interface BoardEvent {
  seq: number;
  op_id: string;
  client_id: string;
  actor: { id: string; username: string };
  kind: Op["kind"];
  data: { card?: Card; id?: string; deleted_ids?: string[] };
}

export interface Ack {
  t: "ack";
  op_id: string;
  seq: number;
  event: BoardEvent;
}

/** Server state at `seq`. */
export interface Confirmed {
  seq: number;
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
  /** ids of cards with an unconfirmed create */
  pending: Set<string>;
}

// --- builders ------------------------------------------------------------------------

const base = (seq: number) => ({ op_id: uuid7(), base_seq: seq });

export function createCard(seq: number, data: Omit<CardCreateData, "id">, id = uuid7()): Op {
  return { ...base(seq), kind: "card.create", data: { id, ...data } };
}

export function setDone(seq: number, id: string, isDone: boolean): Op {
  return { ...base(seq), kind: "card.update", data: { id, fields: { is_done: isDone } } };
}

export function deleteCard(seq: number, id: string): Op {
  return { ...base(seq), kind: "card.delete", data: { id } };
}

/** The op that undoes `op`, given the card as it was before `op` (M3b sends these with
 * `undo: true`). Delete → restore arrives with card.restore in M3b. */
export function inverseOf(op: Op, before: Card | undefined, seq: number): Op | null {
  switch (op.kind) {
    case "card.create":
      return deleteCard(seq, op.data.id);
    case "card.update":
      return before ? setDone(seq, before.id, before.is_done) : null;
    case "card.delete":
      return null;
  }
}

// --- confirmed state -----------------------------------------------------------------

export function confirmedFrom(seq: number, statuses: Status[], cards: Card[]): Confirmed {
  return { seq, statuses, cards: new Map(cards.map((c) => [c.id, c])) };
}

/** Applies a server event in place (caller guarantees seq order). */
export function applyEvent(state: Confirmed, ev: BoardEvent): void {
  if (ev.data.card) state.cards.set(ev.data.card.id, ev.data.card);
  for (const id of ev.data.deleted_ids ?? []) state.cards.delete(id);
  state.seq = ev.seq;
}

// --- view ----------------------------------------------------------------------------

// Keys are ASCII, so JS string order is the server's byte order (COLLATE "C").
const byPosition = (a: Card, b: Card) =>
  a.position < b.position ? -1 : a.position > b.position ? 1 : a.id < b.id ? -1 : 1;

function placeholder(d: CardCreateData): Card {
  return {
    id: d.id,
    number: 0,
    status_id: d.status_id,
    parent_card_id: null,
    position: "",
    title: d.title,
    description: "",
    is_done: false,
    tags: [],
    date: null,
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

/** Applies one pending op to the view in place. Columns touched are already copies. */
export function applyOptimistic(view: BoardView, op: Op): void {
  switch (op.kind) {
    case "card.create": {
      const d = op.data;
      const col = view.columns.get(d.status_id);
      if (!col || findCard(view.columns, d.id)) return;
      // Same neighbour rule as the server: after_id, else before_id, else the end.
      let i = d.after_id ? col.findIndex((c) => c.id === d.after_id) : -1;
      if (i >= 0) i += 1;
      else {
        i = d.before_id ? col.findIndex((c) => c.id === d.before_id) : -1;
        if (i < 0) i = col.length;
      }
      col.splice(i, 0, placeholder(d));
      view.pending.add(d.id);
      return;
    }
    case "card.update": {
      const hit = findCard(view.columns, op.data.id);
      if (hit) hit[0][hit[1]] = { ...hit[0][hit[1]], ...op.data.fields };
      return;
    }
    case "card.delete": {
      const hit = findCard(view.columns, op.data.id);
      if (hit) hit[0].splice(hit[1], 1);
      view.children.delete(op.data.id);
      return;
    }
  }
}

export function buildView(state: Confirmed, pending: readonly Op[]): BoardView {
  const columns = new Map<string, Card[]>(state.statuses.map((s) => [s.id, []]));
  const children = new Map<string, ChildCount>();
  for (const c of state.cards.values()) {
    if (c.parent_card_id) {
      const n = children.get(c.parent_card_id) ?? { done: 0, total: 0 };
      n.total += 1;
      if (c.is_done) n.done += 1;
      children.set(c.parent_card_id, n);
    } else if (c.status_id) {
      columns.get(c.status_id)?.push(c);
    }
  }
  for (const col of columns.values()) col.sort(byPosition);
  const view: BoardView = {
    seq: state.seq,
    statuses: state.statuses,
    columns,
    children,
    pending: new Set(),
  };
  for (const op of pending) applyOptimistic(view, op);
  return view;
}
