import { describe, expect, it } from "vitest";
import {
  applyEvent,
  buildView,
  confirmedFrom,
  createCard,
  deleteCard,
  inverseOf,
  setDone,
  type BoardEvent,
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

describe("events", () => {
  const ev = (seq: number, data: BoardEvent["data"]): BoardEvent => ({
    seq,
    op_id: "o",
    client_id: "c",
    actor: { id: "u", username: "u" },
    kind: "card.create",
    data,
  });

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
});

describe("inverses", () => {
  it("create → delete, update → old value; delete waits for card.restore (M3b)", () => {
    const create = createCard(5, { status_id: TODO.id, title: "x" }, "n1");
    expect(inverseOf(create, undefined, 6)).toMatchObject({
      kind: "card.delete",
      data: { id: "n1" },
      base_seq: 6,
    });
    const before = card("c1", "a0", { is_done: false });
    expect(inverseOf(setDone(5, "c1", true), before, 6)).toMatchObject({
      kind: "card.update",
      data: { id: "c1", fields: { is_done: false } },
    });
    expect(inverseOf(deleteCard(5, "c1"), before, 6)).toBeNull();
  });

  it("gives every op a fresh op_id", () => {
    expect(setDone(1, "c", true).op_id).not.toBe(setDone(1, "c", true).op_id);
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
