import { describe, expect, it, vi } from "vitest";
import type { Card } from "../src/lib/api/boards";
import { ApiError } from "../src/lib/api/client";
import { createCard, deleteCard, setDone, type Ack, type Op } from "../src/lib/sync/ops";
import { BoardStore, CLIENT_ID } from "../src/lib/sync/store";
import { card, detail, TODO } from "./fixtures";

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
});
