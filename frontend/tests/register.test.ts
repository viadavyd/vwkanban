import { describe, expect, it } from "vitest";
import { pasteOp, snapshot } from "../src/lib/sync/register";
import { card, TODO } from "./fixtures";

describe("register", () => {
  const parent = card("c1", "a0", { title: "P", tags: ["ui"], date: "2026-12-01", is_done: true });
  const kids = [
    card("k1", "a0", { status_id: null, parent_card_id: "c1", title: "one" }),
    card("k2", "a1", { status_id: null, parent_card_id: "c1", title: "two", is_done: true }),
  ];

  it("snapshots content without identity", () => {
    const snap = snapshot(parent, kids);
    expect(snap).toEqual({
      title: "P",
      description: "",
      tags: ["ui"],
      date: "2026-12-01",
      is_done: true,
      children: [
        { title: "one", description: "", tags: [], date: null, is_done: false },
        { title: "two", description: "", tags: [], date: null, is_done: true },
      ],
    });
    snap.tags.push("x");
    expect(parent.tags).toEqual(["ui"]); // a copy, not a reference
  });

  it("pastes as a new card with new ids for it and its children, every time", () => {
    const snap = snapshot(parent, kids);
    const a = pasteOp(3, snap, TODO.id, "c9");
    const b = pasteOp(3, snap, TODO.id);
    if (a.kind !== "card.create" || b.kind !== "card.create") throw new Error(a.kind);
    expect(a.data).toMatchObject({ status_id: TODO.id, after_id: "c9", title: "P", is_done: true });
    expect(b.data.after_id).toBeUndefined();
    const all = [
      a.data.id,
      b.data.id,
      ...a.data.children!.map((c) => c.id),
      ...b.data.children!.map((c) => c.id),
    ];
    expect(new Set(all).size).toBe(6);
    expect(all).not.toContain("c1");
    expect(a.data.children!.map((c) => c.title)).toEqual(["one", "two"]);
  });

  it("sends no children field for a card without children", () => {
    const op = pasteOp(1, snapshot(parent, []), TODO.id);
    expect("children" in op.data).toBe(false);
  });
});
