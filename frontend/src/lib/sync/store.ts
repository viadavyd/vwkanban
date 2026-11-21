// Board store (plan §3.4, HTTP transport until the WebSocket in M4): confirmed server state
// plus a queue of pending ops; the view is confirmed with pending applied on top.
//
// Ops go out one at a time and in order, so acks arrive in seq order. A network error or
// 5xx retries the same op (same op_id: the server dedups resends). A reject drops the op,
// applies the server's `current` and reports the message.
//
// Undo (plan §4.3 `u`): an undoable op pushes its inverse, computed from the view just
// before it. `undo()` queues that inverse with `undo: true`; its `base_seq` is the seq the
// original op got, filled in when the inverse is sent. Ops go out in order, so by then the
// original has been acked (or rejected, and then the undo is dropped).

import { postOp, type BoardDetail, type Card } from "../api/boards";
import { ApiError } from "../api/client";
import { uuid7 } from "../ids";
import {
  applyEvent,
  buildView,
  childrenOf,
  confirmedFrom,
  inverseOf,
  type BoardEvent,
  type BoardView,
  type Confirmed,
  type Op,
} from "./ops";

/** One id per browser tab. */
export const CLIENT_ID = uuid7();

const RETRY_MIN_MS = 500;
const RETRY_MAX_MS = 8000;
export const UNDO_DEPTH = 50;

interface UndoEntry {
  /** op_id of the op this undoes */
  of: string;
  inverse: Op;
}

export interface StoreHooks {
  /** Called with the new view after every change. */
  onchange: (view: BoardView) => void;
  /** A reject or an error worth showing. */
  onmessage: (message: string) => void;
  onloggedout: () => void;
  /** The board is gone or we lost access. */
  ongone: () => void;
  /** Fetches the board again (resync). */
  load: () => Promise<BoardDetail>;
  send?: typeof postOp;
  /** setTimeout, injectable for tests. */
  later?: (fn: () => void, ms: number) => void;
}

export class BoardStore {
  private confirmed: Confirmed;
  private pending: Op[] = [];
  private inflight = false;
  private retryMs = RETRY_MIN_MS;
  private closed = false;
  private undoStack: UndoEntry[] = [];
  /** op_ids whose seq an undo may still need (on the stack, or undone but unacked) */
  private tracked = new Set<string>();
  /** op_id → seq, for tracked ops the server acked */
  private acked = new Map<string, number>();
  /** inverse op_id → the op_id it undoes, for queued undos */
  private undoOf = new Map<string, string>();
  view: BoardView;

  constructor(
    readonly boardId: string,
    detail: BoardDetail,
    private readonly hooks: StoreHooks,
  ) {
    this.confirmed = confirmedFrom(detail.seq, detail.statuses, detail.cards);
    this.view = buildView(this.confirmed, this.pending);
  }

  get seq(): number {
    return this.confirmed.seq;
  }

  get pendingCount(): number {
    return this.pending.length;
  }

  get canUndo(): boolean {
    return this.undoStack.length > 0;
  }

  /** Applies `op` optimistically and queues it for the server. An undoable op can be
   * undone later with `undo()`. */
  submit(op: Op, { undoable = true }: { undoable?: boolean } = {}): void {
    const inverse = undoable ? inverseOf(op, this.view) : null;
    if (inverse) {
      this.undoStack.push({ of: op.op_id, inverse });
      this.tracked.add(op.op_id);
      if (this.undoStack.length > UNDO_DEPTH) this.forget(this.undoStack.shift()!);
    }
    this.pending.push(op);
    this.refresh();
    this.pump();
  }

  /** Queues the inverse of the newest undoable op; returns the inverse, or null if there
   * is nothing to undo. A teammate's newer change makes the server reject it. */
  undo(): Op | null {
    const entry = this.undoStack.pop();
    if (!entry) return null;
    this.undoOf.set(entry.inverse.op_id, entry.of);
    this.pending.push(entry.inverse);
    this.refresh();
    this.pump();
    return entry.inverse;
  }

  /** A card's live children (confirmed), for register snapshots. */
  childrenOf(id: string): Card[] {
    return childrenOf(this.confirmed, id);
  }

  private forget(entry: UndoEntry): void {
    this.tracked.delete(entry.of);
    this.acked.delete(entry.of);
  }

  close(): void {
    this.closed = true;
  }

  private refresh(): void {
    this.view = buildView(this.confirmed, this.pending);
    this.hooks.onchange(this.view);
  }

  private async pump(): Promise<void> {
    if (this.inflight || this.closed || this.pending.length === 0) return;
    const op = this.withBaseSeq(this.pending[0]);
    if (!op) {
      // An undo of an op the server rejected: there is nothing to undo.
      this.pending.shift();
      this.refresh();
      return this.pump();
    }
    this.pending[0] = op;
    this.inflight = true;
    const send = this.hooks.send ?? postOp;
    try {
      const ack = await send(this.boardId, CLIENT_ID, op);
      this.retryMs = RETRY_MIN_MS;
      this.pending.shift();
      this.settled(op, ack.seq);
      await this.applyAck(ack.event);
    } catch (e) {
      if (!(e instanceof ApiError)) throw e;
      if (e.status === 0 || e.status >= 500 || e.status === 429) {
        this.inflight = false;
        const later = this.hooks.later ?? ((fn, ms) => setTimeout(fn, ms));
        later(() => this.pump(), this.retryMs);
        this.retryMs = Math.min(this.retryMs * 2, RETRY_MAX_MS);
        return;
      }
      this.pending.shift();
      this.settled(op, null);
      this.reject(op, e);
    } finally {
      this.inflight = false;
    }
    if (!this.closed) this.pump();
  }

  /** For a queued undo: the op with `base_seq` = the undone op's seq (null if that op was
   * rejected). Other ops as they are. */
  private withBaseSeq(op: Op): Op | null {
    const of = this.undoOf.get(op.op_id);
    if (of === undefined) return op;
    const seq = this.acked.get(of);
    if (seq !== undefined) return { ...op, base_seq: seq };
    this.undoOf.delete(op.op_id);
    return null;
  }

  /** Bookkeeping once the server answered `op` (seq = null: rejected). */
  private settled(op: Op, seq: number | null): void {
    const of = this.undoOf.get(op.op_id);
    if (of !== undefined) {
      // An undo was answered: its original's seq is no longer needed.
      this.undoOf.delete(op.op_id);
      this.tracked.delete(of);
      this.acked.delete(of);
      return;
    }
    if (!this.tracked.has(op.op_id)) return;
    if (seq !== null) return void this.acked.set(op.op_id, seq);
    // Rejected: it never happened, so there is nothing to undo.
    this.tracked.delete(op.op_id);
    this.undoStack = this.undoStack.filter((u) => u.of !== op.op_id);
  }

  private async applyAck(ev: BoardEvent): Promise<void> {
    if (ev.seq <= this.confirmed.seq) {
      this.refresh(); // already in confirmed (a resync got it first)
    } else if (ev.seq === this.confirmed.seq + 1) {
      applyEvent(this.confirmed, ev);
      this.refresh();
    } else {
      // Another tab wrote in between: until the WebSocket (M4), fetch the missing state.
      await this.resync();
    }
  }

  private reject(op: Op, e: ApiError): void {
    if (e.status === 401) return this.hooks.onloggedout();
    if (e.status === 404 && e.code === "not_found" && !("current" in e.details)) {
      return this.hooks.ongone(); // the board itself (no op reject body)
    }
    this.hooks.onmessage(e.message);
    if (op.kind.startsWith("status.")) {
      this.refresh();
      return void this.resync(); // columns are few: reload them rather than patch
    }
    const id = op.data.id;
    const current = e.details.current as Card | null | undefined;
    if (current) this.confirmed.cards.set(current.id, current);
    else if (op.kind !== "card.create" && op.kind !== "card.restore") {
      this.confirmed.cards.delete(id);
    }
    this.refresh();
    // A create or move into a column that is gone: our columns are stale.
    if (e.code === "gone" && (op.kind === "card.create" || op.kind === "card.move")) {
      void this.resync();
    }
  }

  /** Replaces confirmed with a fresh load (pending ops stay on top). */
  async resync(): Promise<void> {
    try {
      const d = await this.hooks.load();
      if (d.seq >= this.confirmed.seq) {
        this.confirmed = confirmedFrom(d.seq, d.statuses, d.cards);
      }
      this.refresh();
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) this.hooks.onloggedout();
      else if (e instanceof ApiError && e.status === 404) this.hooks.ongone();
      else this.hooks.onmessage(e instanceof ApiError ? e.message : "Something went wrong");
    }
  }
}
