import { describe, expect, it, vi } from "vitest";
import type { Card } from "../src/lib/api/boards";
import { ApiError } from "../src/lib/api/client";
import {
  createCard,
  deleteCard,
  deleteStatus,
  moveCard,
  setDone,
  type Ack,
  type Op,
} from "../src/lib/sync/ops";
import { BoardStore, CLIENT_ID, UNDO_DEPTH } from "../src/lib/sync/store";
import { card, detail, DOING, TODO } from "./fixtures";

/** A fake server: each call waits until the test resolves it. */
function fakeServer() {
  const calls: { op: Op; resolve: (a: Ack) => void; reject: (e: unknown) => void }[] = [];
  const send = vi.fn(
    (_board: string, _client: string, op: Op) =>
      new Promise<Ack>((resolve, reject) => calls.push({ op, resolve, reject })),
  );
  return { calls, send };
}

const ack = (op: Op, seq: number, data: Ack["event"]["data"]): Ack => ({
  t: "ack",
  op_id: op.op_id,
  seq,
  event: {
    seq,
    op_id: op.op_id,
    client_id: CLIENT_ID,
    actor: { id: "u", username: "u" },
    kind: op.kind,
    data,
  },
});

const flush = () => new Promise((r) => setTimeout(r, 0));

function setup(cards: Card[] = [card("c1", "a0")], seq = 1) {
  const server = fakeServer();
  const timers: (() => void)[] = [];
  const hooks = {
    onchange: vi.fn(),
    onmessage: vi.fn(),
    onloggedout: vi.fn(),
    ongone: vi.fn(),
    load: vi.fn(async () => detail(9, [card("c1", "a0"), card("c9", "a9")])),
    send: server.send,
    later: (fn: () => void) => timers.push(fn),
  };
  const store = new BoardStore("b", detail(seq, cards), hooks);
  const col = () => store.view.columns.get(TODO.id)!.map((c) => c.id);
  return { store, server, hooks, timers, col };
}

describe("BoardStore", () => {
  it("applies optimistically, sends one op at a time in order, confirms on ack", async () => {
    const { store, server, col } = setup();
    const create = createCard(1, { status_id: TODO.id, title: "new", after_id: "c1" }, "n1");
    const toggle = setDone(1, "n1", true);
    store.submit(create);
    store.submit(toggle);
    expect(col()).toEqual(["c1", "n1"]);
    expect(store.view.pending.has("n1")).toBe(true);
    expect(store.view.columns.get(TODO.id)![1].is_done).toBe(true);
    expect(server.calls.map((c) => c.op)).toEqual([create]); // only the first is in flight

    server.calls[0].resolve(ack(create, 2, { card: card("n1", "a1", { number: 2 }) }));
    await flush();
    expect(server.calls.map((c) => c.op)).toEqual([create, toggle]);
    expect(store.view.pending.has("n1")).toBe(false);
    expect(store.view.columns.get(TODO.id)![1].number).toBe(2);
    expect(store.view.columns.get(TODO.id)![1].is_done).toBe(true); // still pending on top

    server.calls[1].resolve(
      ack(toggle, 3, { card: card("n1", "a1", { number: 2, is_done: true }) }),
    );
    await flush();
    expect(store.seq).toBe(3);
    expect(store.pendingCount).toBe(0);
  });

  it("retries network errors with the same op_id and backs off", async () => {
    const { store, server, timers, col } = setup();
    const del = deleteCard(1, "c1");
    store.submit(del);
    server.calls[0].reject(new ApiError(0, "network", "offline"));
    await flush();
    expect(col()).toEqual([]); // still applied optimistically
    expect(timers).toHaveLength(1);
    timers[0]();
    server.calls[1].reject(new ApiError(502, "error", "bad gateway"));
    await flush();
    timers[1]();
    expect(server.calls.map((c) => c.op.op_id)).toEqual([del.op_id, del.op_id, del.op_id]);
    server.calls[2].resolve(ack(del, 2, { id: "c1", deleted_ids: ["c1"] }));
    await flush();
    expect(store.pendingCount).toBe(0);
    expect(col()).toEqual([]);
  });

  it("drops a rejected op, applies current and reports it", async () => {
    const { store, server, hooks, col } = setup([card("c1", "a0"), card("c2", "a1")]);
    store.submit(setDone(1, "c1", true));
    store.submit(setDone(1, "c2", true));
    server.calls[0].reject(
      new ApiError(410, "gone", "#1 was deleted", { op_id: "x", current: null }),
    );
    await flush();
    expect(hooks.onmessage).toHaveBeenCalledWith("#1 was deleted");
    expect(col()).toEqual(["c2"]); // gone from confirmed
    expect(server.calls).toHaveLength(2); // the queue moves on
    server.calls[1].reject(
      new ApiError(409, "conflict", "changed", { current: card("c2", "a1", { title: "srv" }) }),
    );
    await flush();
    expect(store.view.columns.get(TODO.id)![0]).toMatchObject({ title: "srv", is_done: false });
  });

  it("resyncs on a seq gap (another tab wrote) and on a create into a gone column", async () => {
    const { store, server, hooks, col } = setup();
    const del = deleteCard(1, "c1");
    store.submit(del);
    server.calls[0].resolve(ack(del, 5, { id: "c1", deleted_ids: ["c1"] }));
    await flush();
    expect(hooks.load).toHaveBeenCalledTimes(1);
    expect(store.seq).toBe(9);
    expect(col()).toEqual(["c1", "c9"]); // the fresh load wins

    store.submit(createCard(9, { status_id: TODO.id, title: "x" }, "n2"));
    server.calls[1].reject(
      new ApiError(410, "gone", "that column no longer exists", { current: null }),
    );
    await flush();
    expect(hooks.load).toHaveBeenCalledTimes(2);
    expect(col()).toEqual(["c1", "c9"]);
  });

  it("maps 401 to logged out and a board 404 to gone", async () => {
    const { store, server, hooks } = setup([card("c1", "a0"), card("c2", "a1")]);
    store.submit(setDone(1, "c1", true));
    server.calls[0].reject(new ApiError(401, "unauthenticated", "not logged in"));
    await flush();
    expect(hooks.onloggedout).toHaveBeenCalled();
    store.submit(setDone(1, "c2", true));
    server.calls[1].reject(new ApiError(404, "not_found", "board not found"));
    await flush();
    expect(hooks.ongone).toHaveBeenCalled();
  });

  it("undoes with base_seq = the seq the undone op got, sent with undo: true", async () => {
    const { store, server, col } = setup([card("c1", "a0"), card("c2", "a1")]);
    const mv = moveCard(1, "c1", DOING.id);
    store.submit(mv);
    server.calls[0].resolve(ack(mv, 2, { card: card("c1", "a0", { status_id: DOING.id }) }));
    await flush();
    expect(col()).toEqual(["c2"]);

    const inv = store.undo()!;
    expect(col()).toEqual(["c1", "c2"]); // optimistic: back before c2
    await flush();
    expect(server.calls[1].op).toMatchObject({
      op_id: inv.op_id,
      kind: "card.move",
      undo: true,
      base_seq: 2,
      data: { id: "c1", status_id: TODO.id, before_id: "c2" },
    });
    server.calls[1].resolve(ack(inv, 3, { card: card("c1", "a0") }));
    await flush();
    expect(store.canUndo).toBe(false);
    expect(store.undo()).toBeNull(); // undos are not undoable (no redo in the MVP)
  });

  it("can undo an op that is still in flight: its base_seq is filled in once acked", async () => {
    const { store, server } = setup();
    const toggle = setDone(1, "c1", true);
    store.submit(toggle);
    store.undo();
    expect(store.view.columns.get(TODO.id)![0].is_done).toBe(false);
    server.calls[0].resolve(ack(toggle, 2, { card: card("c1", "a0", { is_done: true }) }));
    await flush();
    expect(server.calls[1].op).toMatchObject({ undo: true, base_seq: 2, kind: "card.update" });
  });

  it("drops the undo entry of a rejected op, and a queued undo of it", async () => {
    const { store, server } = setup([card("c1", "a0"), card("c2", "a1")]);
    const first = setDone(1, "c1", true);
    const second = setDone(1, "c2", true);
    store.submit(first);
    store.submit(second);
    store.undo(); // undoes `second`, which is still queued behind `first`
    server.calls[0].resolve(ack(first, 2, { card: card("c1", "a0", { is_done: true }) }));
    await flush();
    server.calls[1].reject(new ApiError(410, "gone", "#2 was deleted", { current: null }));
    await flush();
    expect(server.calls).toHaveLength(2); // the undo of `second` is never sent
    expect(store.pendingCount).toBe(0);
    expect(store.canUndo).toBe(true); // `first` can still be undone
    store.undo();
    await flush();
    expect(server.calls[2].op).toMatchObject({ base_seq: 2, data: { id: "c1" } });
  });

  it("keeps the last 50 undoable ops", async () => {
    const { store, server } = setup();
    for (let i = 0; i < UNDO_DEPTH + 5; i++) {
      const op = setDone(1, "c1", i % 2 === 0);
      store.submit(op);
      await flush();
      server.calls
        .at(-1)!
        .resolve(ack(op, i + 2, { card: card("c1", "a0", { is_done: i % 2 === 0 }) }));
      await flush();
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

  it("resyncs after a rejected column op", async () => {
    const { store, server, hooks } = setup();
    store.submit(deleteStatus(1, TODO.id));
    expect(store.view.statuses.map((s) => s.id)).toEqual([DOING.id]);
    server.calls[0].reject(
      new ApiError(422, "validation", "column 'Todo' is not empty", { current: TODO }),
    );
    await flush();
    expect(hooks.onmessage).toHaveBeenCalledWith("column 'Todo' is not empty");
    expect(hooks.load).toHaveBeenCalledTimes(1);
    expect(store.view.statuses.map((s) => s.id)).toEqual([TODO.id, DOING.id]);
  });

  it("exposes a card's children for snapshots", () => {
    const { store } = setup([
      card("c1", "a0"),
      card("k2", "a1", { status_id: null, parent_card_id: "c1" }),
      card("k1", "a0", { status_id: null, parent_card_id: "c1" }),
    ]);
    expect(store.childrenOf("c1").map((c) => c.id)).toEqual(["k1", "k2"]);
  });
});
