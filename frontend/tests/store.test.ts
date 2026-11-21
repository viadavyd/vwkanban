import { describe, expect, it, vi } from "vitest";
import type { Card } from "../src/lib/api/boards";
import { ApiError } from "../src/lib/api/client";
import {
  createCard,
  deleteCard,
  deleteStatus,
  moveCard,
  setDone,
  updateCard,
  type BoardEvent,
  type Op,
} from "../src/lib/sync/ops";
import type { SocketHooks, SyncStatus } from "../src/lib/sync/socket";
import { BoardStore, CLIENT_ID, GAP_WAIT_MS, UNDO_DEPTH } from "../src/lib/sync/store";
import { card, detail, DOING, TODO } from "./fixtures";

const OTHER = "other-tab";

/** A fake board socket: records what the store sends; the test plays the server. */
function fakeSocket() {
  let hooks!: SocketHooks;
  let up = false;
  const sent: Op[] = [];
  const hellos: { client_id: string; last_seq: number }[] = [];
  const connect = (h: SocketHooks) => {
    hooks = h;
    return {
      send: (msg: object) => {
        if (!up) return false;
        const { t, ...op } = msg as { t: string } & Op;
        expect(t).toBe("op");
        sent.push(op as Op);
        return true;
      },
      close: vi.fn(),
    };
  };
  const status = (s: SyncStatus) => {
    up = s === "live";
    hooks.onstatus(s);
  };
  return {
    connect,
    sent,
    hellos,
    /** connect (or reconnect) and get the welcome */
    welcome(seq: number, presence = [{ user_id: "u", username: "u" }]) {
      hellos.push(hooks.hello());
      status("live");
      hooks.onmessage({ t: "welcome", seq, presence });
    },
    drop() {
      status("reconnecting");
    },
    final: (code: number) => hooks.onfinal(code),
    msg: (m: Parameters<SocketHooks["onmessage"]>[0]) => hooks.onmessage(m),
    event(seq: number, op: Op | { op_id: string; kind: Op["kind"] }, data: BoardEvent["data"]) {
      const own = sent.some((s) => s.op_id === op.op_id);
      hooks.onmessage({
        t: "event",
        seq,
        op_id: op.op_id,
        client_id: own ? CLIENT_ID : OTHER,
        actor: { id: "u", username: own ? "me" : "bob" },
        kind: op.kind,
        data,
      });
    },
    ack: (op: Op, seq: number) => hooks.onmessage({ t: "ack", op_id: op.op_id, seq }),
    /** the event then the ack, as the server sends them */
    answer(op: Op, seq: number, data: BoardEvent["data"]) {
      this.event(seq, op, data);
      this.ack(op, seq);
    },
    reject: (op: Op, code: string, message: string, current: unknown = null) =>
      hooks.onmessage({ t: "reject", op_id: op.op_id, code, message, current }),
  };
}

const remote = (kind: Op["kind"]) => ({ op_id: `r-${Math.random()}`, kind });
const flush = () => new Promise((r) => setTimeout(r, 0));

function setup(cards: Card[] = [card("c1", "a0")], seq = 1, live = true) {
  const server = fakeSocket();
  const timers: (() => void)[] = [];
  const hooks = {
    onchange: vi.fn(),
    onmessage: vi.fn(),
    onloggedout: vi.fn(),
    ongone: vi.fn(),
    onstatus: vi.fn(),
    onpresence: vi.fn(),
    onremote: vi.fn(),
    onreject: vi.fn(),
    load: vi.fn(async () => detail(9, [card("c1", "a0"), card("c9", "a9")])),
    connect: server.connect,
    later: (fn: () => void) => void timers.push(fn),
  };
  const store = new BoardStore("b", detail(seq, cards), hooks);
  if (live) server.welcome(seq);
  const col = (id = TODO.id) => store.view.columns.get(id)!.map((c) => c.id);
  return { store, server, hooks, timers, col };
}

describe("BoardStore: sending", () => {
  it("applies optimistically, sends in order without waiting, confirms on its event", () => {
    const { store, server, col } = setup();
    const create = createCard(1, { status_id: TODO.id, title: "new", after_id: "c1" }, "n1");
    const toggle = setDone(1, "n1", true);
    store.submit(create);
    store.submit(toggle);
    expect(col()).toEqual(["c1", "n1"]);
    expect(store.view.pending.has("n1")).toBe(true);
    expect(server.sent).toEqual([create, toggle]); // pipelined

    server.answer(create, 2, { card: card("n1", "a1", { number: 2 }) });
    expect(store.view.pending.has("n1")).toBe(false);
    expect(store.view.columns.get(TODO.id)![1]).toMatchObject({ number: 2, is_done: true });
    expect(store.pendingCount).toBe(1);

    server.answer(toggle, 3, { card: card("n1", "a1", { number: 2, is_done: true }) });
    expect(store.pendingCount).toBe(0);
    expect(store.seq).toBe(3);
  });

  it("queues while disconnected and sends after the welcome, with last_seq", () => {
    const { store, server } = setup([card("c1", "a0")], 4, false);
    const toggle = setDone(4, "c1", true);
    store.submit(toggle);
    expect(server.sent).toEqual([]);
    expect(store.view.columns.get(TODO.id)![0].is_done).toBe(true);
    server.welcome(4);
    expect(server.hellos).toEqual([{ client_id: CLIENT_ID, last_seq: 4 }]);
    expect(server.sent).toEqual([toggle]);
  });

  it("re-sends unanswered ops with the same op_id after a reconnect, no duplicates", () => {
    const { store, server, col } = setup([card("c1", "a0"), card("c2", "a1")]);
    const a = setDone(1, "c1", true);
    const b = deleteCard(1, "c2");
    store.submit(a);
    store.submit(b);
    server.answer(a, 2, { card: card("c1", "a0", { is_done: true }) });
    server.drop();
    const c = moveCard(2, "c1", DOING.id);
    store.submit(c);
    expect(server.sent.map((o) => o.op_id)).toEqual([a.op_id, b.op_id]);

    server.welcome(2);
    expect(server.hellos.at(-1)).toEqual({ client_id: CLIENT_ID, last_seq: 2 });
    expect(server.sent.map((o) => o.op_id)).toEqual([a.op_id, b.op_id, b.op_id, c.op_id]);
    server.answer(b, 3, { id: "c2", deleted_ids: ["c2"] });
    server.ack(b, 3); // the stored ack of the resend: harmless
    server.answer(c, 4, { card: card("c1", "a0", { is_done: true, status_id: DOING.id }) });
    expect(store.pendingCount).toBe(0);
    expect(col()).toEqual([]);
    expect(col(DOING.id)).toEqual(["c1"]);
  });

  it("reports connection status and presence", () => {
    const { server, hooks } = setup();
    expect(hooks.onstatus).toHaveBeenLastCalledWith("live");
    expect(hooks.onpresence).toHaveBeenLastCalledWith([{ user_id: "u", username: "u" }]);
    server.drop();
    expect(hooks.onstatus).toHaveBeenLastCalledWith("reconnecting");
    const users = [
      { user_id: "u", username: "u" },
      { user_id: "b", username: "bob" },
    ];
    server.msg({ t: "presence", users });
    expect(hooks.onpresence).toHaveBeenLastCalledWith(users);
  });

  it("maps final closes: 4401 logged out, 4403/4404 gone, others a message", () => {
    for (const [code, hook, arg] of [
      [4401, "onloggedout", undefined],
      [4403, "ongone", "you are no longer a member of that board"],
      [4404, "ongone", "that board was deleted"],
      [4400, "onmessage", "the server refused the live connection"],
    ] as const) {
      const { server, hooks } = setup();
      server.final(code);
      if (arg === undefined) expect(hooks[hook]).toHaveBeenCalled();
      else expect(hooks[hook]).toHaveBeenCalledWith(arg);
    }
  });

  it("closes the socket on close()", () => {
    const server = fakeSocket();
    const transport = { send: () => true, close: vi.fn() };
    const store = new BoardStore("b", detail(1, []), {
      onchange: vi.fn(),
      onmessage: vi.fn(),
      onloggedout: vi.fn(),
      ongone: vi.fn(),
      load: vi.fn(),
      connect: (h) => (server.connect(h), transport),
    });
    store.close();
    expect(transport.close).toHaveBeenCalled();
  });
});

describe("BoardStore: remote events", () => {
  it("applies another client's event and keeps pending ops on top (rebase)", () => {
    const { store, server, hooks, col } = setup([card("c1", "a0"), card("c2", "a1")]);
    const toggle = setDone(1, "c1", true);
    store.submit(toggle);
    // bob moved c1 to Doing first; our toggle is still pending on top of it.
    const ev = remote("card.move");
    server.event(2, ev, { card: card("c1", "a0", { status_id: DOING.id }) });
    expect(col()).toEqual(["c2"]);
    expect(store.view.columns.get(DOING.id)![0]).toMatchObject({ id: "c1", is_done: true });
    expect(hooks.onremote).toHaveBeenCalledWith(expect.objectContaining({ op_id: ev.op_id }));
    server.answer(toggle, 3, { card: card("c1", "a0", { status_id: DOING.id, is_done: true }) });
    expect(store.pendingCount).toBe(0);
    expect(store.view.columns.get(DOING.id)![0].is_done).toBe(true);
  });

  it("applies events strictly in seq order: a later one waits for the gap to fill", () => {
    const { store, server, hooks, col } = setup();
    server.event(3, remote("card.create"), { card: card("c3", "a3") });
    expect(store.seq).toBe(1);
    expect(col()).toEqual(["c1"]);
    server.event(2, remote("card.create"), { card: card("c2", "a2") });
    expect(store.seq).toBe(3);
    expect(col()).toEqual(["c1", "c2", "c3"]);
    expect(hooks.load).not.toHaveBeenCalled();
  });

  it("resyncs when a gap doesn't fill within GAP_WAIT_MS", async () => {
    const { store, server, hooks, timers, col } = setup();
    expect(GAP_WAIT_MS).toBe(1000);
    server.event(5, remote("card.create"), { card: card("c5", "a5") });
    expect(timers).toHaveLength(1);
    timers[0]();
    await flush();
    expect(hooks.load).toHaveBeenCalledTimes(1);
    expect(store.seq).toBe(9);
    expect(col()).toEqual(["c1", "c9"]); // the fresh load wins; event 5 is older
  });

  it("applies buffered events past the fresh state after a resync", async () => {
    const { store, server, hooks, timers, col } = setup();
    server.event(10, remote("card.create"), { card: card("c10", "b0") });
    timers[0]();
    await flush(); // load returns seq 9: event 10 is next
    expect(hooks.load).toHaveBeenCalledTimes(1);
    expect(store.seq).toBe(10);
    expect(col()).toEqual(["c1", "c9", "c10"]);
  });

  it("ignores events it already has", () => {
    const { store, server, col } = setup([card("c1", "a0")], 5);
    server.event(5, remote("card.delete"), { id: "c1", deleted_ids: ["c1"] });
    expect(col()).toEqual(["c1"]);
    expect(store.seq).toBe(5);
  });

  it("resyncs when the server says so", async () => {
    const { store, server, hooks } = setup();
    server.msg({ t: "resync" });
    await flush();
    expect(hooks.load).toHaveBeenCalledTimes(1);
    expect(store.seq).toBe(9);
  });

  it("an ack whose event a resync already folded in still clears the op", async () => {
    const { store, server, hooks } = setup();
    const toggle = setDone(1, "c1", true);
    store.submit(toggle);
    server.msg({ t: "resync" });
    await flush();
    server.event(4, toggle, { card: card("c1", "a0", { is_done: true }) }); // ≤ 9: ignored
    server.ack(toggle, 4);
    expect(store.pendingCount).toBe(0);
    expect(hooks.load).toHaveBeenCalledTimes(1);
  });
});

describe("BoardStore: rejects", () => {
  it("drops a rejected op, applies current and reports it", () => {
    const { store, server, hooks, col } = setup([card("c1", "a0"), card("c2", "a1")]);
    const a = setDone(1, "c1", true);
    const b = setDone(1, "c2", true);
    store.submit(a);
    store.submit(b);
    server.reject(a, "gone", "#1 was deleted by bob");
    expect(hooks.onmessage).toHaveBeenCalledWith("#1 was deleted by bob");
    expect(hooks.onreject).toHaveBeenCalledWith(a, "gone", "#1 was deleted by bob");
    expect(col()).toEqual(["c2"]); // gone from confirmed
    server.reject(b, "conflict", "changed", card("c2", "a1", { title: "srv" }));
    expect(store.view.columns.get(TODO.id)![0]).toMatchObject({ title: "srv", is_done: false });
    expect(store.pendingCount).toBe(0);
  });

  it("resyncs after a create into a gone column, and after a rejected column op", async () => {
    const { store, server, hooks } = setup();
    const create = createCard(1, { status_id: TODO.id, title: "x" }, "n2");
    store.submit(create);
    server.reject(create, "gone", "that column no longer exists");
    await flush();
    expect(hooks.load).toHaveBeenCalledTimes(1);

    const del = deleteStatus(9, TODO.id);
    store.submit(del);
    expect(store.view.statuses.map((s) => s.id)).toEqual([DOING.id]);
    server.reject(del, "validation", "column 'Todo' is not empty", TODO);
    await flush();
    expect(hooks.load).toHaveBeenCalledTimes(2);
    expect(store.view.statuses.map((s) => s.id)).toEqual([TODO.id, DOING.id]);
  });

  it("maps a 401/404 during resync to logged out / gone", async () => {
    const { store, hooks } = setup();
    hooks.load.mockRejectedValueOnce(new ApiError(401, "unauthenticated", "no"));
    await store.resync();
    expect(hooks.onloggedout).toHaveBeenCalled();
    hooks.load.mockRejectedValueOnce(new ApiError(404, "not_found", "board not found"));
    await store.resync();
    expect(hooks.ongone).toHaveBeenCalledWith("that board was deleted");
  });
});

describe("BoardStore: undo", () => {
  it("undoes with base_seq = the seq the undone op got, sent with undo: true", () => {
    const { store, server, col } = setup([card("c1", "a0"), card("c2", "a1")]);
    const mv = moveCard(1, "c1", DOING.id);
    store.submit(mv);
    server.answer(mv, 2, { card: card("c1", "a0", { status_id: DOING.id }) });
    expect(col()).toEqual(["c2"]);

    const inv = store.undo()!;
    expect(col()).toEqual(["c1", "c2"]); // optimistic: back before c2
    expect(server.sent[1]).toMatchObject({
      op_id: inv.op_id,
      kind: "card.move",
      undo: true,
      base_seq: 2,
      data: { id: "c1", status_id: TODO.id, before_id: "c2" },
    });
    server.answer({ ...inv, base_seq: 2 }, 3, { card: card("c1", "a0") });
    expect(store.canUndo).toBe(false);
    expect(store.undo()).toBeNull(); // undos are not undoable (no redo in the MVP)
  });

  it("holds an undo back until its original is acked (event first, then ack)", () => {
    const { store, server } = setup();
    const toggle = setDone(1, "c1", true);
    store.submit(toggle);
    store.undo();
    expect(store.view.columns.get(TODO.id)![0].is_done).toBe(false);
    expect(server.sent).toEqual([toggle]);
    server.event(2, toggle, { card: card("c1", "a0", { is_done: true }) });
    expect(server.sent).toHaveLength(1); // the event alone doesn't give the seq yet
    server.ack(toggle, 2);
    expect(server.sent[1]).toMatchObject({ undo: true, base_seq: 2, kind: "card.update" });
  });

  it("drops the undo entry of a rejected op, and a queued undo of it", () => {
    const { store, server } = setup([card("c1", "a0"), card("c2", "a1")]);
    const first = setDone(1, "c1", true);
    const second = setDone(1, "c2", true);
    store.submit(first);
    store.submit(second);
    store.undo(); // undoes `second`, which is in flight behind `first`
    server.answer(first, 2, { card: card("c1", "a0", { is_done: true }) });
    server.reject(second, "gone", "#2 was deleted by bob");
    expect(server.sent).toHaveLength(2); // the undo of `second` is never sent
    expect(store.pendingCount).toBe(0);
    expect(store.canUndo).toBe(true); // `first` can still be undone
    store.undo();
    expect(server.sent[2]).toMatchObject({ base_seq: 2, data: { id: "c1" } });
  });

  it("keeps the last 50 undoable ops", () => {
    const { store, server } = setup();
    for (let i = 0; i < UNDO_DEPTH + 5; i++) {
      const op = setDone(1, "c1", i % 2 === 0);
      store.submit(op);
      server.answer(op, i + 2, { card: card("c1", "a0", { is_done: i % 2 === 0 }) });
    }
    let n = 0;
    while (store.undo()) n++;
    expect(n).toBe(UNDO_DEPTH);
  });

  it("has nothing to undo at first, and skips ops it can't invert", () => {
    const { store } = setup();
    expect(store.undo()).toBeNull();
    store.submit(setDone(1, "missing", true));
    expect(store.canUndo).toBe(false);
    store.submit(setDone(1, "c1", true), { undoable: false });
    expect(store.canUndo).toBe(false);
  });
});

describe("BoardStore: snapshots", () => {
  it("exposes a card's children for snapshots", () => {
    const { store } = setup([
      card("c1", "a0"),
      card("k2", "a1", { status_id: null, parent_card_id: "c1" }),
      card("k1", "a0", { status_id: null, parent_card_id: "c1" }),
    ]);
    expect(store.childrenOf("c1").map((c) => c.id)).toEqual(["k1", "k2"]);
  });
});

describe("BoardStore: M5 answers and card-scoped undo", () => {
  it("resolves submit() with the ack's seq, or with the reject", async () => {
    const { store, server } = setup();
    const edit = updateCard(1, "c1", { description: "mine" });
    const answer = store.submit(edit);
    server.answer(edit, 2, { card: card("c1", "a0", { description: "mine" }) });
    expect(await answer).toEqual({ ok: true, seq: 2 });

    const stale = updateCard(1, "c1", { description: "late" });
    const refused = store.submit(stale);
    const current = card("c1", "a0", { description: "theirs" });
    server.reject(stale, "conflict", "#1's description was changed by bob", current);
    expect(await refused).toEqual({
      ok: false,
      code: "conflict",
      message: "#1's description was changed by bob",
      current,
    });
    // The view shows the server's value; the draft is the field's business.
    expect(store.view.columns.get(TODO.id)![0].description).toBe("theirs");
  });

  it("undoes the newest op only if the filter accepts it", async () => {
    const { store, server } = setup([card("c1", "a0"), card("c2", "a1")]);
    const a = setDone(1, "c1", true);
    const b = setDone(1, "c2", true);
    store.submit(a);
    store.submit(b);
    server.answer(a, 2, { card: card("c1", "a0", { is_done: true }) });
    server.answer(b, 3, { card: card("c2", "a1", { is_done: true }) });
    const onC1 = (inv: Op) => "id" in inv.data && inv.data.id === "c1";
    expect(store.undo(onC1)).toBeNull(); // the newest op was on c2
    expect(store.canUndo).toBe(true);
    const inv = store.undo((op) => "id" in op.data && op.data.id === "c2");
    expect(inv).toMatchObject({ kind: "card.update", undo: true, data: { id: "c2" } });
    await flush();
    expect(server.sent.at(-1)).toMatchObject({ op_id: inv!.op_id, base_seq: 3 });
  });
});
