import { describe, expect, it, vi } from "vitest";
import {
  BACKOFF_MAX_MS,
  BACKOFF_MIN_MS,
  BoardSocket,
  boardSocketUrl,
  OFFLINE_AFTER_MS,
  PING_EVERY_MS,
  PONG_TIMEOUT_MS,
  type SyncStatus,
  type WebSocketLike,
} from "../src/lib/sync/socket";

class FakeWs implements WebSocketLike {
  readyState = 0;
  sent: unknown[] = [];
  closedWith: number | undefined;
  onopen: WebSocketLike["onopen"] = null;
  onmessage: WebSocketLike["onmessage"] = null;
  onclose: WebSocketLike["onclose"] = null;
  onerror: WebSocketLike["onerror"] = null;
  send(data: string) {
    this.sent.push(JSON.parse(data));
  }
  close(code?: number) {
    this.closedWith = code;
  }
  // test side
  open() {
    this.readyState = 1;
    this.onopen?.({});
  }
  receive(msg: object) {
    this.onmessage?.({ data: JSON.stringify(msg) });
  }
  serverClose(code: number) {
    this.readyState = 3;
    this.onclose?.({ code });
  }
}

function setup() {
  const sockets: FakeWs[] = [];
  let now = 0;
  let online = true;
  let nextId = 1;
  const timers = new Map<number, { at: number; fn: () => void }>();
  const env = {
    open: () => {
      const ws = new FakeWs();
      sockets.push(ws);
      return ws;
    },
    later: (fn: () => void, ms: number) => {
      const id = nextId++;
      timers.set(id, { at: now + ms, fn });
      return id;
    },
    cancel: (id: number) => void timers.delete(id),
    now: () => now,
    online: () => online,
  };
  /** Advances the clock, running due timers in order. */
  const advance = (ms: number) => {
    const end = now + ms;
    for (;;) {
      const due = [...timers.entries()]
        .filter(([, t]) => t.at <= end)
        .sort((a, b) => a[1].at - b[1].at)[0];
      if (!due) break;
      timers.delete(due[0]);
      now = due[1].at;
      due[1].fn();
    }
    now = end;
  };
  const statuses: SyncStatus[] = [];
  const hooks = {
    hello: vi.fn(() => ({ client_id: "tab", last_seq: 7 })),
    onmessage: vi.fn(),
    onstatus: (s: SyncStatus) => void statuses.push(s),
    onfinal: vi.fn(),
  };
  const socket = new BoardSocket("ws://x/api/boards/b/ws", hooks, env);
  const last = () => sockets.at(-1)!;
  const goLive = () => {
    last().open();
    last().receive({ t: "welcome", seq: 7, presence: [] });
  };
  return {
    socket,
    sockets,
    hooks,
    statuses,
    advance,
    last,
    goLive,
    setOnline: (v: boolean) => (online = v),
  };
}

describe("BoardSocket", () => {
  it("builds ws:// or wss:// from the page's location", () => {
    expect(boardSocketUrl("b1", { protocol: "http:", host: "kanban.test" })).toBe(
      "ws://kanban.test/api/boards/b1/ws",
    );
    expect(boardSocketUrl("b1", { protocol: "https:", host: "k.test:8443" })).toBe(
      "wss://k.test:8443/api/boards/b1/ws",
    );
  });

  it("says hello on open and is live after the welcome", () => {
    const { socket, last, hooks, statuses } = setup();
    expect(socket.send({ t: "op" })).toBe(false); // not live yet
    last().open();
    expect(last().sent).toEqual([{ t: "hello", client_id: "tab", last_seq: 7 }]);
    expect(socket.live).toBe(false);
    last().receive({ t: "welcome", seq: 7, presence: [] });
    expect(statuses).toEqual(["live"]);
    expect(hooks.onmessage).toHaveBeenCalledWith({ t: "welcome", seq: 7, presence: [] });
    expect(socket.send({ t: "op", op_id: "o" })).toBe(true);
    expect(last().sent.at(-1)).toEqual({ t: "op", op_id: "o" });
  });

  it("passes server messages on, and ignores garbage", () => {
    const { last, goLive, hooks } = setup();
    goLive();
    last().receive({ t: "ack", op_id: "o", seq: 8 });
    last().onmessage?.({ data: "{nope" });
    expect(hooks.onmessage).toHaveBeenLastCalledWith({ t: "ack", op_id: "o", seq: 8 });
  });

  it("reconnects with backoff 0.5 s → 8 s and resets it once live", () => {
    const { sockets, last, advance, goLive, statuses } = setup();
    goLive();
    last().serverClose(1006);
    expect(statuses.at(-1)).toBe("reconnecting");
    const waits: number[] = [];
    for (let i = 0; i < 6; i++) {
      const before = sockets.length;
      let waited = 0;
      while (sockets.length === before) {
        advance(100);
        waited += 100;
      }
      waits.push(waited);
      last().serverClose(1006);
    }
    expect(BACKOFF_MIN_MS).toBe(500);
    expect(BACKOFF_MAX_MS).toBe(8000);
    expect(waits).toEqual([500, 1000, 2000, 4000, 8000, 8000]);
    advance(8000);
    goLive();
    expect(statuses.at(-1)).toBe("live");
    last().serverClose(1006);
    advance(499);
    const n = sockets.length;
    advance(1);
    expect(sockets.length).toBe(n + 1); // back to 0.5 s
  });

  it("each reconnect says hello again with the then-current last_seq", () => {
    const { last, goLive, advance, hooks } = setup();
    goLive();
    hooks.hello.mockReturnValue({ client_id: "tab", last_seq: 12 });
    last().serverClose(1006);
    advance(BACKOFF_MIN_MS);
    last().open();
    expect(last().sent).toEqual([{ t: "hello", client_id: "tab", last_seq: 12 }]);
  });

  it("shows offline when the browser is offline or retries fail for 30 s", () => {
    const a = setup();
    a.goLive();
    a.setOnline(false);
    a.last().serverClose(1006);
    expect(a.statuses.at(-1)).toBe("offline");

    const b = setup();
    b.last().serverClose(1006);
    expect(b.statuses.at(-1)).toBe("reconnecting");
    let t = 0;
    while (t < OFFLINE_AFTER_MS) {
      b.advance(BACKOFF_MAX_MS);
      t += BACKOFF_MAX_MS;
      b.last().serverClose(1006);
    }
    expect(b.statuses.at(-1)).toBe("offline");
    // and it keeps trying
    const n = b.sockets.length;
    b.advance(BACKOFF_MAX_MS);
    expect(b.sockets.length).toBe(n + 1);
  });

  it("retries at once when the browser comes back online", () => {
    const { last, sockets, socket, goLive } = setup();
    goLive();
    last().serverClose(1006);
    const n = sockets.length;
    socket.retryNow();
    expect(sockets.length).toBe(n + 1);
  });

  it("stops on final close codes and reports them", () => {
    for (const code of [4400, 4401, 4403, 4404]) {
      const { last, goLive, advance, sockets, hooks, statuses } = setup();
      goLive();
      last().serverClose(code);
      expect(hooks.onfinal).toHaveBeenCalledWith(code);
      expect(statuses.at(-1)).toBe("offline");
      advance(60_000);
      expect(sockets).toHaveLength(1);
    }
  });

  it("reconnects after other closes (rate limit, too slow, server restart)", () => {
    for (const code of [4429, 1013, 1001, 1006]) {
      const { last, goLive, advance, sockets, hooks } = setup();
      goLive();
      last().serverClose(code);
      advance(BACKOFF_MIN_MS);
      expect(sockets).toHaveLength(2);
      expect(hooks.onfinal).not.toHaveBeenCalled();
    }
  });

  it("pings every 25 s and drops a link that doesn't pong", () => {
    const { last, goLive, advance, sockets, statuses } = setup();
    goLive();
    advance(PING_EVERY_MS);
    expect(last().sent.at(-1)).toEqual({ t: "ping" });
    last().receive({ t: "pong" });
    advance(PONG_TIMEOUT_MS); // answered: nothing happens
    expect(sockets).toHaveLength(1);

    advance(PING_EVERY_MS - PONG_TIMEOUT_MS);
    expect(last().sent.filter((m) => (m as { t: string }).t === "ping")).toHaveLength(2);
    advance(PONG_TIMEOUT_MS);
    expect(sockets[0].closedWith).toBe(4000);
    expect(statuses.at(-1)).toBe("reconnecting");
    advance(BACKOFF_MIN_MS);
    expect(sockets).toHaveLength(2);
  });

  it("close() stops everything", () => {
    const { socket, last, goLive, advance, sockets } = setup();
    goLive();
    socket.close();
    expect(last().closedWith).toBe(1000);
    advance(60_000);
    expect(sockets).toHaveLength(1);
    expect(socket.send({ t: "op" })).toBe(false);
  });
});
