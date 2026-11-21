// Board store (plan §3.4): confirmed server state plus a queue of pending ops; the view is
// confirmed with pending applied on top, rebuilt after every change.
//
// Transport: the board WebSocket (socket.ts). Pending ops are sent in order as soon as the
// socket is live, several in flight at once; after a reconnect every unanswered op is sent
// again with its op_id (the server dedups). While disconnected, ops queue in memory.
//
// Events are applied strictly in seq order. One past confirmed.seq + 1 is buffered for up
// to GAP_WAIT_MS waiting for the gap to fill, then the store resyncs (re-GETs the board).
// Our own event drops the op from pending; another client's lands in confirmed and the
// pending ops are re-applied on top. A reject drops the op, applies the server's
// `current` and reports the message.
//
// Undo (plan §4.3 `u`): an undoable op pushes its inverse, computed from the view just
// before it. `undo()` queues that inverse with `undo: true`; its `base_seq` is the seq the
// original op got, so the inverse is held back until the original is acked (or dropped if
// the original was rejected).

import type { BoardDetail, Card } from "../api/boards";
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
import type { PresenceUser, ServerMsg, SocketHooks, SyncStatus } from "./socket";

/** One id per browser tab. */
export const CLIENT_ID = uuid7();

export const UNDO_DEPTH = 50;
/** How long an out-of-order event waits for the gap before a resync (plan §3.4). */
export const GAP_WAIT_MS = 1000;

interface UndoEntry {
  /** op_id of the op this undoes */
  of: string;
  inverse: Op;
}

/** What the store needs from the socket. */
export interface Transport {
  send(msg: object): boolean;
  close(): void;
}

export interface StoreHooks {
  /** Called with the new view after every change. */
  onchange: (view: BoardView) => void;
  /** A reject or an error worth showing. */
  onmessage: (message: string) => void;
  onloggedout: () => void;
  /** The board is gone or we lost access; the message says which. */
  ongone: (message: string) => void;
  /** Connection status (the top bar's dot). */
  onstatus?: (status: SyncStatus) => void;
  /** Who else has the board open. */
  onpresence?: (users: PresenceUser[]) => void;
  /** Another client's event (after it was applied). */
  onremote?: (ev: BoardEvent) => void;
  /** An op of ours the server refused (after the store handled it). */
  onreject?: (op: Op, code: string, message: string) => void;
  /** Fetches the board again (resync). */
  load: () => Promise<BoardDetail>;
  /** Opens the board socket; it calls back into `hooks`. */
  connect: (hooks: SocketHooks) => Transport;
  /** setTimeout, injectable for tests. */
  later?: (fn: () => void, ms: number) => void;
}

const GONE_MESSAGES: Record<number, string> = {
  4403: "you are no longer a member of that board",
  4404: "that board was deleted",
};

export class BoardStore {
  private confirmed: Confirmed;
  private pending: Op[] = [];
  /** pending[0..sent) went out on the current connection */
  private sent = 0;
  private live = false;
  private closed = false;
  /** out-of-order events, by seq */
  private buffer = new Map<number, BoardEvent>();
  private gapTimer = false;
  private resyncing = false;
  private undoStack: UndoEntry[] = [];
  /** op_ids whose seq an undo may still need (on the stack, or undone but unacked) */
  private tracked = new Set<string>();
  /** op_id → seq, for tracked ops the server acked */
  private acked = new Map<string, number>();
  /** inverse op_id → the op_id it undoes, for queued undos */
  private undoOf = new Map<string, string>();
  /** Own ops whose event came before their ack (the usual order): kept until the ack, so
   * the undo bookkeeping gets the seq. */
  private answered = new Map<string, Op>();
  private readonly socket: Transport;
  view: BoardView;

  constructor(
    readonly boardId: string,
    detail: BoardDetail,
    private readonly hooks: StoreHooks,
  ) {
    this.confirmed = confirmedFrom(detail.seq, detail.statuses, detail.cards);
    this.view = buildView(this.confirmed, this.pending);
    this.socket = hooks.connect({
      hello: () => ({ client_id: CLIENT_ID, last_seq: this.confirmed.seq }),
      onmessage: (m) => this.received(m),
      onstatus: (s) => this.status(s),
      onfinal: (code) => this.final(code),
    });
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

  close(): void {
    this.closed = true;
    this.socket.close();
  }

  private forget(entry: UndoEntry): void {
    this.tracked.delete(entry.of);
    this.acked.delete(entry.of);
  }

  private refresh(): void {
    this.view = buildView(this.confirmed, this.pending);
    this.hooks.onchange(this.view);
  }

  private later(fn: () => void, ms: number): void {
    (this.hooks.later ?? ((f, t) => setTimeout(f, t)))(fn, ms);
  }

  // --- sending -------------------------------------------------------------------------

  /** Sends every unsent pending op, in order, while the socket is live. */
  private pump(): void {
    while (this.live && !this.closed && this.sent < this.pending.length) {
      const op = this.withBaseSeq(this.pending[this.sent]);
      if (op === "wait") return; // an undo whose original isn't acked yet
      if (op === null) {
        // An undo of an op the server rejected: there is nothing to undo.
        this.pending.splice(this.sent, 1);
        this.refresh();
        continue;
      }
      this.pending[this.sent] = op;
      if (!this.socket.send({ t: "op", ...op })) return;
      this.sent += 1;
    }
  }

  /** For a queued undo: the op with `base_seq` = the undone op's seq, "wait" until that op
   * is acked, null if it was rejected. Other ops as they are. */
  private withBaseSeq(op: Op): Op | null | "wait" {
    const of = this.undoOf.get(op.op_id);
    if (of === undefined) return op;
    const seq = this.acked.get(of);
    if (seq !== undefined) return { ...op, base_seq: seq };
    if (this.answered.has(of) || this.pending.some((p) => p.op_id === of)) return "wait";
    this.undoOf.delete(op.op_id);
    return null;
  }

  /** Removes an answered op from pending; returns it (undefined if it wasn't there). */
  private take(opId: string): Op | undefined {
    const i = this.pending.findIndex((p) => p.op_id === opId);
    if (i < 0) return undefined;
    const [op] = this.pending.splice(i, 1);
    if (i < this.sent) this.sent -= 1;
    return op;
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

  // --- receiving -----------------------------------------------------------------------

  private status(s: SyncStatus): void {
    if (s !== "live") {
      this.live = false;
      this.sent = 0; // unanswered ops go out again after the next welcome
    }
    this.hooks.onstatus?.(s);
  }

  private final(code: number): void {
    this.live = false;
    if (code === 4401) return this.hooks.onloggedout();
    const gone = GONE_MESSAGES[code];
    if (gone) return this.hooks.ongone(gone);
    this.hooks.onmessage("the server refused the live connection");
  }

  private received(m: ServerMsg): void {
    if (this.closed) return;
    switch (m.t) {
      case "welcome":
        this.buffer.clear();
        this.live = true;
        this.sent = 0;
        this.hooks.onpresence?.(m.presence);
        if (m.seq < this.confirmed.seq) void this.resync();
        this.pump();
        return;
      case "event":
        return this.event(m);
      case "ack": {
        const op = this.take(m.op_id);
        if (op) {
          // Its event was already folded into confirmed by a resync.
          this.settled(op, m.seq);
          this.refresh();
        } else {
          const done = this.answered.get(m.op_id);
          if (done) this.settled(done, m.seq);
          this.answered.delete(m.op_id);
        }
        this.pump(); // an undo may have been waiting for this
        return;
      }
      case "reject": {
        const op = this.take(m.op_id);
        if (!op) return;
        this.settled(op, null);
        this.reject(op, m.code, m.message, m.current as Card | null | undefined);
        this.pump();
        return;
      }
      case "presence":
        return this.hooks.onpresence?.(m.users);
      case "resync":
        return void this.resync();
    }
  }

  private event(ev: BoardEvent): void {
    if (ev.seq <= this.confirmed.seq) return;
    if (ev.seq > this.confirmed.seq + 1) {
      this.buffer.set(ev.seq, ev);
      return this.armGap();
    }
    this.apply(ev);
    this.drain();
    this.refresh();
  }

  private apply(ev: BoardEvent): void {
    applyEvent(this.confirmed, ev);
    const own = this.take(ev.op_id);
    if (own) this.answered.set(ev.op_id, own);
    else if (ev.client_id !== CLIENT_ID) this.hooks.onremote?.(ev);
  }

  /** Resyncs if the gap is still open after GAP_WAIT_MS. */
  private armGap(): void {
    if (this.gapTimer || !this.buffer.size) return;
    this.gapTimer = true;
    this.later(() => {
      this.gapTimer = false;
      if (this.buffer.size) void this.resync();
    }, GAP_WAIT_MS);
  }

  /** Applies buffered events that are now next in line. */
  private drain(): void {
    for (const seq of [...this.buffer.keys()])
      if (seq <= this.confirmed.seq) this.buffer.delete(seq);
    let next: BoardEvent | undefined;
    while ((next = this.buffer.get(this.confirmed.seq + 1))) {
      this.buffer.delete(next.seq);
      this.apply(next);
    }
  }

  private reject(op: Op, code: string, message: string, current: Card | null | undefined): void {
    this.hooks.onmessage(message);
    this.hooks.onreject?.(op, code, message);
    if (op.kind.startsWith("status.")) {
      this.refresh();
      return void this.resync(); // columns are few: reload them rather than patch
    }
    const id = op.data.id;
    if (current) this.confirmed.cards.set(current.id, current);
    else if (op.kind !== "card.create" && op.kind !== "card.restore") {
      this.confirmed.cards.delete(id);
    }
    this.refresh();
    // A create or move into a column that is gone: our columns are stale.
    if (code === "gone" && (op.kind === "card.create" || op.kind === "card.move")) {
      void this.resync();
    }
  }

  /** Replaces confirmed with a fresh load (pending ops stay on top). */
  async resync(): Promise<void> {
    if (this.resyncing) return;
    this.resyncing = true;
    try {
      const d = await this.hooks.load();
      if (this.closed) return;
      if (d.seq >= this.confirmed.seq) {
        this.confirmed = confirmedFrom(d.seq, d.statuses, d.cards);
      }
      this.drain();
      this.refresh();
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) this.hooks.onloggedout();
      else if (e instanceof ApiError && e.status === 404) this.hooks.ongone(GONE_MESSAGES[4404]);
      else this.hooks.onmessage(e instanceof ApiError ? e.message : "Something went wrong");
    } finally {
      this.resyncing = false;
      this.armGap(); // events past the fresh state that still have a gap before them
    }
  }
}
