import { describe, expect, it } from "vitest";
import {
  applyEvent,
  buildView,
  cardById,
  confirmedFrom,
  createCard,
  createChild,
  createStatus,
  deleteCard,
  deleteStatus,
  inverseOf,
  moveCard,
  moveStatus,
  restoreCard,
  setDone,
  updateCard,
  updateStatus,
  type BoardEvent,
  type Op,
} from "../src/lib/sync/ops";
import { uuid7 } from "../src/lib/ids";
import { card, DOING, TODO } from "./fixtures";

const ids = (v: ReturnType<typeof buildView>, s = TODO.id) => v.columns.get(s)!.map((c) => c.id);

const state = () =>
  confirmedFrom(
    5,
    [TODO, DOING],
    [
      card("c2", "a1"),
      card("c1", "a0"),
      card("c3", "a2"),
      card("k1", "a0", { status_id: null, parent_card_id: "c1", is_done: true }),
      card("k2", "a1", { status_id: null, parent_card_id: "c1" }),
    ],
  );

describe("view", () => {
  it("orders columns by position, byte-wise", () => {
    const s = confirmedFrom(1, [TODO], [card("c1", "a0V"), card("c2", "Zz"), card("c3", "a0")]);
    expect(ids(buildView(s, []))).toEqual(["c2", "c3", "c1"]);
  });

  it("counts children for the n/m badge and keeps them out of columns", () => {
    const v = buildView(state(), []);
    expect(ids(v)).toEqual(["c1", "c2", "c3"]);
    expect(v.children.get("c1")).toEqual({ done: 1, total: 2 });
    expect(v.columns.get(DOING.id)).toEqual([]);
  });

  it("places pending creates by after_id, else before_id, else at the end", () => {
    const v = buildView(state(), [
      createCard(5, { status_id: TODO.id, title: "A", after_id: "c1" }, "pa"),
      createCard(5, { status_id: TODO.id, title: "B", before_id: "c1" }, "pb"),
      createCard(5, { status_id: TODO.id, title: "C", after_id: "gone" }, "pc"),
      createCard(5, { status_id: DOING.id, title: "D" }, "pd"),
      createCard(5, { status_id: TODO.id, title: "E", after_id: "gone", before_id: "c3" }, "pe"),
    ]);
    expect(ids(v)).toEqual(["pb", "c1", "pa", "c2", "pe", "c3", "pc"]);
    expect(ids(v, DOING.id)).toEqual(["pd"]);
    expect(v.pending).toEqual(new Set(["pa", "pb", "pc", "pd", "pe"]));
    expect(v.columns.get(TODO.id)![2]).toMatchObject({ number: 0, title: "A" });
  });

  it("applies pending toggles and deletes without touching unchanged cards", () => {
    const s = state();
    const before = buildView(s, []);
    const v = buildView(s, [setDone(5, "c2", true), deleteCard(5, "c1")]);
    expect(ids(v)).toEqual(["c2", "c3"]);
    expect(v.columns.get(TODO.id)![0].is_done).toBe(true);
    expect(s.cards.get("c2")!.is_done).toBe(false); // confirmed untouched
    expect(v.columns.get(TODO.id)![1]).toBe(before.columns.get(TODO.id)![2]); // same object
  });
});

const ev = (
  seq: number,
  data: BoardEvent["data"],
  kind: Op["kind"] = "card.create",
): BoardEvent => ({
  seq,
  op_id: "o",
  client_id: "c",
  actor: { id: "u", username: "u" },
  kind,
  data,
});

describe("events", () => {
  it("applies creates, updates and deletes (with children)", () => {
    const s = state();
    applyEvent(s, ev(6, { card: card("c4", "a3") }));
    applyEvent(s, ev(7, { card: card("c2", "a1", { is_done: true }) }));
    applyEvent(s, ev(8, { id: "c1", deleted_ids: ["c1", "k1", "k2"] }));
    const v = buildView(s, []);
    expect(s.seq).toBe(8);
    expect(ids(v)).toEqual(["c2", "c3", "c4"]);
    expect(v.columns.get(TODO.id)![0].is_done).toBe(true);
    expect(v.children.size).toBe(0);
  });

  it("applies restores with children, pastes, and column events in position order", () => {
    const s = state();
    applyEvent(s, ev(6, { id: "c1", deleted_ids: ["c1", "k1", "k2"] }));
    applyEvent(
      s,
      ev(7, {
        card: card("c1", "a0"),
        children: [card("k1", "a0", { status_id: null, parent_card_id: "c1" })],
      }),
    );
    expect(buildView(s, []).children.get("c1")).toEqual({ done: 0, total: 1 });
    applyEvent(
      s,
      ev(
        8,
        { status: { id: "s-r", name: "Review", color: "red", position: "a0V" } },
        "status.create",
      ),
    );
    applyEvent(s, ev(9, { status: { ...TODO, position: "a2" } }, "status.move"));
    expect(s.statuses.map((x) => x.id)).toEqual(["s-r", DOING.id, TODO.id]);
    applyEvent(s, ev(10, { id: "s-r", purged_ids: ["gone1"] }, "status.delete"));
    expect(s.statuses.map((x) => x.id)).toEqual([DOING.id, TODO.id]);
    expect(s.seq).toBe(10);
  });

  it("keeps confirmed columns in position order from the load", () => {
    const s = confirmedFrom(1, [{ ...TODO, position: "a5" }, DOING], []);
    expect(s.statuses.map((x) => x.id)).toEqual([DOING.id, TODO.id]);
  });
});

describe("inverses", () => {
  const v = () => buildView(state(), []);

  it("gives every op kind an inverse marked undo, from the view before the op", () => {
    const cases: [Op, Partial<Op>][] = [
      [
        createCard(5, { status_id: TODO.id, title: "x" }, "n1"),
        { kind: "card.delete", data: { id: "n1" } },
      ],
      [
        setDone(5, "c1", true),
        { kind: "card.update", data: { id: "c1", fields: { is_done: false } } },
      ],
      [deleteCard(5, "c2"), { kind: "card.restore", data: { id: "c2" } }],
      [restoreCard(5, "c2"), { kind: "card.delete", data: { id: "c2" } }],
      [
        moveCard(5, "c2", DOING.id),
        {
          kind: "card.move",
          data: { id: "c2", status_id: TODO.id, after_id: "c1", before_id: "c3" },
        },
      ],
      [
        moveCard(5, "c1", DOING.id),
        { kind: "card.move", data: { id: "c1", status_id: TODO.id, before_id: "c2" } },
      ],
      [
        createStatus(5, "New", "red", {}, "s-new"),
        { kind: "status.delete", data: { id: "s-new" } },
      ],
      [
        updateStatus(5, TODO.id, { name: "Backlog" }),
        { kind: "status.update", data: { id: TODO.id, name: "Todo" } },
      ],
      [
        moveStatus(5, TODO.id, { after_id: DOING.id }),
        { kind: "status.move", data: { id: TODO.id, before_id: DOING.id } },
      ],
      [
        deleteStatus(5, DOING.id),
        {
          kind: "status.create",
          data: { id: DOING.id, name: "Doing", color: "blue", after_id: TODO.id },
        },
      ],
    ];
    for (const [op, want] of cases) {
      const inv = inverseOf(op, v());
      expect(inv, op.kind).toMatchObject({ ...want, undo: true });
      expect(inv!.data).toEqual(want.data); // exactly these fields
      expect(inv!.op_id).not.toBe(op.op_id);
    }
  });

  it("has nothing to undo for a card or column that isn't there", () => {
    expect(inverseOf(setDone(5, "nope", true), v())).toBeNull();
    expect(inverseOf(moveCard(5, "nope", TODO.id), v())).toBeNull();
    expect(inverseOf(deleteStatus(5, "nope"), v())).toBeNull();
  });

  it("gives every op a fresh op_id", () => {
    expect(setDone(1, "c", true).op_id).not.toBe(setDone(1, "c", true).op_id);
  });
});

describe("M3b optimistic ops", () => {
  it("moves cards across and within columns by the neighbour rule", () => {
    const s = state();
    const v = buildView(s, [
      moveCard(5, "c1", DOING.id),
      moveCard(5, "c3", TODO.id, { before_id: "c2" }),
    ]);
    expect(ids(v)).toEqual(["c3", "c2"]);
    expect(ids(v, DOING.id)).toEqual(["c1"]);
    expect(v.columns.get(DOING.id)![0].status_id).toBe(DOING.id);
    expect(s.cards.get("c1")!.status_id).toBe(TODO.id); // confirmed untouched
    expect(v.children.get("c1")).toEqual({ done: 1, total: 2 }); // children follow
  });

  it("shows a pasted card with its child count", () => {
    const op = createCard(5, {
      status_id: TODO.id,
      title: "copy",
      after_id: "c1",
      tags: ["ui"],
      children: [
        { id: "k8", title: "a", is_done: true },
        { id: "k9", title: "b" },
      ],
    });
    const v = buildView(state(), [op]);
    expect(ids(v)).toEqual(["c1", op.data.id, "c2", "c3"]);
    expect(v.columns.get(TODO.id)![1].tags).toEqual(["ui"]);
    expect(v.children.get(op.data.id)).toEqual({ done: 1, total: 2 });
  });

  it("creates, renames, moves and deletes columns", () => {
    const s = state();
    const names = (x: ReturnType<typeof buildView>) => x.statuses.map((st) => st.name);
    let v = buildView(s, [createStatus(5, "Review", "red", { after_id: TODO.id }, "s-r")]);
    expect(names(v)).toEqual(["Todo", "Review", "Doing"]);
    expect(v.columns.get("s-r")).toEqual([]);
    v = buildView(s, [
      updateStatus(5, TODO.id, { color: "green" }),
      moveStatus(5, TODO.id, { after_id: DOING.id }),
    ]);
    expect(names(v)).toEqual(["Doing", "Todo"]);
    expect(v.statuses[1].color).toBe("green");
    v = buildView(s, [deleteStatus(5, DOING.id)]);
    expect(names(v)).toEqual(["Todo"]);
    expect(v.columns.has(DOING.id)).toBe(false);
    expect(s.statuses.map((st) => st.name)).toEqual(["Todo", "Doing"]); // confirmed untouched
  });

  it("waits for the ack to show a restored card", () => {
    const s = state();
    applyEvent(s, ev(6, { id: "c1", deleted_ids: ["c1", "k1", "k2"] }));
    expect(ids(buildView(s, [restoreCard(6, "c1")]))).toEqual(["c2", "c3"]);
  });
});

describe("uuid7", () => {
  it("is a version-7 UUID that sorts by time", () => {
    const a = uuid7(1_700_000_000_000);
    const b = uuid7(1_700_000_000_001);
    expect(a).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(a < b).toBe(true);
    expect(a.slice(0, 13)).toBe("018bcfe5-6800");
  });
});

describe("M5 children and text fields", () => {
  const kidIds = (v: ReturnType<typeof buildView>, parent = "c1") =>
    (v.kids.get(parent) ?? []).map((c) => c.id);

  it("lists children in position order and derives the badge from them", () => {
    const v = buildView(state(), []);
    expect(kidIds(v)).toEqual(["k1", "k2"]);
    expect(cardById(v, "k2")?.parent_card_id).toBe("c1");
    expect(cardById(v, "c3")?.id).toBe("c3");
    expect(cardById(v, "nope")).toBeUndefined();
  });

  it("applies pending child creates, toggles, edits and deletes", () => {
    const at = createChild(5, "c1", "between", { after_id: "k1" }, "k9");
    const top = createChild(5, "c1", "first", { before_id: "k1" }, "k0");
    const toggle = setDone(5, "k2", true);
    const edit = updateCard(5, "k1", { title: "renamed" });
    const v = buildView(state(), [at, top, toggle, edit]);
    expect(kidIds(v)).toEqual(["k0", "k1", "k9", "k2"]);
    expect(v.pending.has("k9")).toBe(true);
    expect(cardById(v, "k9")).toMatchObject({ parent_card_id: "c1", status_id: null, number: 0 });
    expect(cardById(v, "k1")?.title).toBe("renamed");
    expect(v.children.get("c1")).toEqual({ done: 2, total: 4 });
    expect(ids(v)).toEqual(["c1", "c2", "c3"]); // children never show in a column

    const gone = buildView(state(), [deleteCard(5, "k1")]);
    expect(kidIds(gone)).toEqual(["k2"]);
    expect(gone.children.get("c1")).toEqual({ done: 0, total: 1 });
    // The parent deleted: no badge, and a child create under it shows nothing.
    const orphan = buildView(state(), [deleteCard(5, "c1"), createChild(5, "c1", "x", {}, "kx")]);
    expect(orphan.kids.has("c1")).toBe(false);
    expect(orphan.children.has("c1")).toBe(false);
  });

  it("applies text-field updates to top-level cards", () => {
    const op = updateCard(5, "c2", {
      title: "T",
      description: "d",
      tags: ["a", "b"],
      date: "2026-12-01",
    });
    expect(cardById(buildView(state(), [op]), "c2")).toMatchObject({
      title: "T",
      description: "d",
      tags: ["a", "b"],
      date: "2026-12-01",
    });
  });

  it("applies a child create event", () => {
    const s = state();
    const ev: BoardEvent = {
      seq: 6,
      op_id: "o",
      client_id: "x",
      actor: { id: "u", username: "u" },
      kind: "card.create",
      data: { card: card("k3", "a2", { status_id: null, parent_card_id: "c1" }) },
    };
    applyEvent(s, ev);
    expect(kidIds(buildView(s, []))).toEqual(["k1", "k2", "k3"]);
  });

  it("inverts a text update to exactly the old values it touched", () => {
    const s = confirmedFrom(
      5,
      [TODO],
      [
        card("c1", "a0", { title: "old", tags: ["x"], date: null, description: "keep" }),
        card("k1", "a0", { status_id: null, parent_card_id: "c1", title: "kid" }),
      ],
    );
    const v = buildView(s, []);
    const inv = inverseOf(updateCard(5, "c1", { title: "new", tags: [], date: "2026-01-01" }), v);
    expect(inv).toMatchObject({
      kind: "card.update",
      undo: true,
      data: { id: "c1", fields: { title: "old", tags: ["x"], date: null } },
    });
    expect(Object.keys((inv as Extract<Op, { kind: "card.update" }>).data.fields)).toEqual([
      "title",
      "tags",
      "date",
    ]);
    // Children: their own toggle and title.
    expect(inverseOf(updateCard(5, "k1", { title: "K", is_done: true }), v)).toMatchObject({
      data: { id: "k1", fields: { title: "kid", is_done: false } },
    });
    expect(inverseOf(createChild(5, "c1", "n", {}, "k5"), v)).toMatchObject({
      kind: "card.delete",
      data: { id: "k5" },
    });
  });
});
