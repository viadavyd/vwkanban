import { describe, expect, it } from "vitest";
import { FieldSession, parse, parseTags, textOf } from "../src/lib/editor/session";
import { card } from "./fixtures";

const ME = "me-tab";
const stamp = (seq: number, client = "bob-tab") => ({ seq, client });

describe("field parsers", () => {
  it("titles are trimmed and required", () => {
    expect(parse("title", "  hi ")).toEqual({ ok: true, fields: { title: "hi" } });
    expect(parse("title", "   ")).toMatchObject({ ok: false });
    expect(parse("title", "x".repeat(301))).toMatchObject({ ok: false });
  });

  it("tags split on spaces and commas, deduped, in order", () => {
    expect(parseTags("ui, bug  ui,,docs")).toEqual(["ui", "bug", "docs"]);
    expect(parseTags("")).toEqual([]);
    expect(parseTags("a;b")).toBe("tags can't contain ';'");
    expect(parseTags("x".repeat(31))).toMatch(/at most 30/);
  });

  it("dates are real YYYY-MM-DD days, or empty (no due date)", () => {
    expect(parse("date", "2026-11-30")).toEqual({ ok: true, fields: { date: "2026-11-30" } });
    expect(parse("date", " ")).toEqual({ ok: true, fields: { date: null } });
    for (const bad of ["2026-02-30", "2026-1-5", "tomorrow", "2026-13-01"]) {
      expect(parse("date", bad)).toMatchObject({ ok: false });
    }
  });

  it("descriptions keep their text as is", () => {
    expect(parse("description", " a\n\nb ")).toEqual({
      ok: true,
      fields: { description: " a\n\nb " },
    });
    expect(parse("description", "😀".repeat(20_000))).toMatchObject({ ok: true });
    expect(parse("description", "x".repeat(20_001))).toMatchObject({ ok: false });
  });

  it("shows tags and dates as text", () => {
    const c = card("c1", "a0", { tags: ["a", "b"], date: "2026-01-02" });
    expect(textOf(c, "tags")).toBe("a b");
    expect(textOf(c, "date")).toBe("2026-01-02");
    expect(textOf(card("c2", "a0"), "date")).toBe("");
  });
});

describe("FieldSession", () => {
  const open = (seq = 10) => new FieldSession("c1", "description", "old", seq, ME);

  it("sends nothing while unchanged; the base is frozen at entry", () => {
    const s = open();
    expect(s.save(15)).toBeNull();
    s.draft = "new";
    expect(s.save(15)).toEqual({ fields: { description: "new" }, baseSeq: 10 });
  });

  it("moves the base only on its own ack", () => {
    const s = open();
    s.draft = "one";
    s.save(10);
    s.acked("one", 11);
    expect(s.base).toBe(11);
    expect(s.dirty).toBe(false);
    s.draft = "two"; // `:w` again: no self-conflict, base is our own ack
    expect(s.save(20)).toEqual({ fields: { description: "two" }, baseSeq: 11 });
  });

  it("flags a newer write by someone else without touching the draft", () => {
    const s = open();
    s.draft = "mine";
    s.observe(card("c1", "a0", { description: "theirs", field_meta: { description: stamp(11) } }));
    expect(s.remoteChanged).toBe(true);
    expect(s.needsChoice).toBe(true);
    expect(s.draft).toBe("mine");
    // Our own writes and older ones don't count.
    const t = open();
    t.observe(card("c1", "a0", { field_meta: { description: stamp(12, ME) } }));
    t.observe(card("c1", "a0", { field_meta: { description: stamp(9) } }));
    expect(t.remoteChanged).toBe(false);
  });

  it("a remote write of the same text needs no choice", () => {
    const s = open();
    s.draft = "same";
    s.observe(card("c1", "a0", { description: "same", field_meta: { description: stamp(12) } }));
    expect(s.needsChoice).toBe(false);
    expect(s.base).toBe(12);
    expect(s.save(12)).toBeNull();
  });

  it(":w! sends the draft with the current seq as base", () => {
    const s = open();
    s.draft = "mine";
    s.save(10);
    s.rejected("#1's description was changed by bob");
    expect(s.conflict).toMatch(/bob/);
    expect(s.save(14, true)).toEqual({ fields: { description: "mine" }, baseSeq: 14 });
    expect(s.needsChoice).toBe(false);
  });

  it(":e! takes the remote value and resets the base", () => {
    const s = open();
    s.draft = "mine";
    s.rejected("conflict");
    const text = s.takeTheirs(card("c1", "a0", { description: "theirs" }), 14);
    expect(text).toBe("theirs");
    expect(s).toMatchObject({ draft: "theirs", saved: "theirs", base: 14, conflict: null });
  });

  it("an invalid draft is not sent and says why", () => {
    const s = new FieldSession("c1", "date", "", 3, ME);
    s.draft = "soon";
    expect(s.save(3)).toBeNull();
    expect(s.error).toMatch(/YYYY-MM-DD/);
    s.draft = "2026-12-24";
    expect(s.save(3)).toEqual({ fields: { date: "2026-12-24" }, baseSeq: 3 });
    expect(s.error).toBeNull();
  });
});
