// Board store (plan §3.4, HTTP transport until the WebSocket in M4): confirmed server state
// plus a queue of pending ops; the view is confirmed with pending applied on top.
//
// Ops go out one at a time and in order, so acks arrive in seq order. A network error or
// 5xx retries the same op (same op_id: the server dedups resends). A reject drops the op,
// applies the server's `current` and reports the message.

import { postOp, type BoardDetail, type Card } from "../api/boards";
import { ApiError } from "../api/client";
import { uuid7 } from "../ids";
import {
  applyEvent,
  buildView,
  confirmedFrom,
  type BoardEvent,
  type BoardView,
  type Confirmed,
  type Op,
} from "./ops";

/** One id per browser tab. */
export const CLIENT_ID = uuid7();

const RETRY_MIN_MS = 500;
const RETRY_MAX_MS = 8000;

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

  /** Applies `op` optimistically and queues it for the server. */
  submit(op: Op): void {
    this.pending.push(op);
    this.refresh();
    this.pump();
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
    this.inflight = true;
    const op = this.pending[0];
    const send = this.hooks.send ?? postOp;
    try {
      const ack = await send(this.boardId, CLIENT_ID, op);
      this.retryMs = RETRY_MIN_MS;
      this.pending.shift();
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
      this.reject(op, e);
    } finally {
      this.inflight = false;
    }
    if (!this.closed) this.pump();
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
    const id = op.data.id;
    const current = e.details.current as Card | null | undefined;
    if (current) this.confirmed.cards.set(current.id, current);
    else if (op.kind !== "card.create") this.confirmed.cards.delete(id);
    this.hooks.onmessage(e.message);
    this.refresh();
    if (e.code === "gone" && op.kind === "card.create") void this.resync(); // column gone
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
