// The board WebSocket (plan §3.2, §3.4): connects, says hello, keeps the link alive with
// pings and reconnects with backoff. It knows nothing about board state: the store
// (store.ts) gives it the hello and gets every server message.
//
// Status: `connecting` until the first welcome, then `live`; after a drop `reconnecting`
// while retrying, or `offline` once the browser says so or retries have failed for
// OFFLINE_AFTER_MS. Close codes 4400/4401/4403/4404 are final (no reconnect).

import type { BoardEvent } from "./ops";

export type SyncStatus = "connecting" | "live" | "reconnecting" | "offline";

export interface PresenceUser {
  user_id: string;
  username: string;
}

export type ServerMsg =
  | { t: "welcome"; seq: number; presence: PresenceUser[] }
  | ({ t: "event" } & BoardEvent)
  | { t: "ack"; op_id: string; seq: number }
  | { t: "reject"; op_id: string; code: string; message: string; current: unknown }
  | { t: "presence"; users: PresenceUser[] }
  | { t: "resync" }
  | { t: "pong" };

export const CLOSE = {
  badOrigin: 4400,
  noSession: 4401,
  notMember: 4403,
  boardGone: 4404,
} as const;
const FINAL_CODES: ReadonlySet<number> = new Set(Object.values(CLOSE));

export const BACKOFF_MIN_MS = 500;
export const BACKOFF_MAX_MS = 8000;
export const PING_EVERY_MS = 25_000;
/** No pong within this → the link is dead: drop it and reconnect. */
export const PONG_TIMEOUT_MS = 10_000;
export const OFFLINE_AFTER_MS = 30_000;

/** The parts of WebSocket we use (a fake in tests). */
export interface WebSocketLike {
  readonly readyState: number;
  send(data: string): void;
  close(code?: number): void;
  onopen: ((ev: unknown) => void) | null;
  onmessage: ((ev: { data: unknown }) => void) | null;
  onclose: ((ev: { code: number }) => void) | null;
  onerror: ((ev: unknown) => void) | null;
}

export interface SocketHooks {
  /** The hello to send on every (re)connect: our tab id and confirmed seq. */
  hello: () => { client_id: string; last_seq: number };
  onmessage: (msg: ServerMsg) => void;
  onstatus: (status: SyncStatus) => void;
  /** A final close (bad origin, logged out, removed, board deleted). */
  onfinal: (code: number) => void;
}

export interface SocketEnv {
  open: (url: string) => WebSocketLike;
  later: (fn: () => void, ms: number) => number;
  cancel: (id: number) => void;
  now: () => number;
  /** false while the browser knows it's offline */
  online: () => boolean;
}

const OPEN = 1;

function browserEnv(): SocketEnv {
  return {
    open: (url) => new WebSocket(url) as unknown as WebSocketLike,
    later: (fn, ms) => window.setTimeout(fn, ms),
    cancel: (id) => window.clearTimeout(id),
    now: () => Date.now(),
    online: () => navigator.onLine,
  };
}

export function boardSocketUrl(boardId: string, loc: { protocol: string; host: string }): string {
  const scheme = loc.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${loc.host}/api/boards/${boardId}/ws`;
}

export class BoardSocket {
  private ws: WebSocketLike | null = null;
  private status: SyncStatus = "connecting";
  private backoff = BACKOFF_MIN_MS;
  private failingSince: number | null = null;
  private timer: number | null = null;
  private pingTimer: number | null = null;
  private pongTimer: number | null = null;
  private stopped = false;
  private readonly env: SocketEnv;

  constructor(
    private readonly url: string,
    private readonly hooks: SocketHooks,
    env: Partial<SocketEnv> = {},
  ) {
    this.env = { ...browserEnv(), ...env };
    this.connect();
  }

  get live(): boolean {
    return this.status === "live";
  }

  /** Sends if live; false otherwise (the caller keeps the message queued). */
  send(msg: object): boolean {
    if (!this.live || !this.ws || this.ws.readyState !== OPEN) return false;
    this.ws.send(JSON.stringify(msg));
    return true;
  }

  close(): void {
    this.stopped = true;
    this.clearTimers();
    const ws = this.ws;
    this.ws = null;
    if (ws) {
      ws.onclose = ws.onmessage = ws.onerror = ws.onopen = null;
      ws.close(1000);
    }
  }

  /** The browser came back online: retry now instead of waiting out the backoff. */
  retryNow(): void {
    if (this.stopped || this.ws) return;
    this.clear("timer");
    this.backoff = BACKOFF_MIN_MS;
    this.connect();
  }

  /** The browser went offline. */
  wentOffline(): void {
    if (this.status !== "live") this.setStatus("offline");
  }

  private connect(): void {
    if (this.stopped) return;
    let ws: WebSocketLike;
    try {
      ws = this.env.open(this.url);
    } catch {
      return this.dropped(1006);
    }
    this.ws = ws;
    ws.onopen = () => ws.send(JSON.stringify({ t: "hello", ...this.hooks.hello() }));
    ws.onmessage = (ev) => this.received(ev.data);
    ws.onclose = (ev) => {
      if (this.ws === ws) this.dropped(ev.code);
    };
    ws.onerror = () => {}; // a close follows
  }

  private received(data: unknown): void {
    let msg: ServerMsg;
    try {
      msg = JSON.parse(String(data));
    } catch {
      return;
    }
    if (msg.t === "welcome") {
      this.backoff = BACKOFF_MIN_MS;
      this.failingSince = null;
      this.setStatus("live");
      this.schedulePing();
    } else if (msg.t === "pong") {
      this.clear("pongTimer");
      return;
    }
    this.hooks.onmessage(msg);
  }

  private dropped(code: number): void {
    this.ws = null;
    this.clearTimers();
    if (this.stopped) return;
    if (FINAL_CODES.has(code)) {
      this.stopped = true;
      this.setStatus("offline");
      return this.hooks.onfinal(code);
    }
    const now = this.env.now();
    this.failingSince ??= now;
    const offline = !this.env.online() || now - this.failingSince >= OFFLINE_AFTER_MS;
    this.setStatus(offline ? "offline" : "reconnecting");
    this.timer = this.env.later(() => {
      this.timer = null;
      this.connect();
    }, this.backoff);
    this.backoff = Math.min(this.backoff * 2, BACKOFF_MAX_MS);
  }

  private schedulePing(): void {
    this.clear("pingTimer");
    this.pingTimer = this.env.later(() => {
      this.pingTimer = null;
      if (!this.send({ t: "ping" })) return;
      this.pongTimer = this.env.later(() => {
        this.pongTimer = null;
        const ws = this.ws;
        if (ws) {
          ws.onclose = ws.onmessage = ws.onerror = ws.onopen = null;
          ws.close(4000);
          this.dropped(1006);
        }
      }, PONG_TIMEOUT_MS);
      this.schedulePing();
    }, PING_EVERY_MS);
  }

  private setStatus(s: SyncStatus): void {
    if (s === this.status) return;
    this.status = s;
    this.hooks.onstatus(s);
  }

  private clear(name: "timer" | "pingTimer" | "pongTimer"): void {
    const id = this[name];
    if (id !== null) this.env.cancel(id);
    this[name] = null;
  }

  private clearTimers(): void {
    this.clear("timer");
    this.clear("pingTimer");
    this.clear("pongTimer");
  }
}
