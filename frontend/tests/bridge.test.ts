import { describe, expect, it } from "vitest";
import { isBackKey, shouldLeaveField, snapshotVim, type KeyLike } from "../src/lib/editor/bridge";

const key = (k: string, mods: Partial<KeyLike> = {}): KeyLike => ({
  key: k,
  ctrlKey: false,
  metaKey: false,
  altKey: false,
  shiftKey: false,
  ...mods,
});

describe("isBackKey", () => {
  it("accepts Esc and Ctrl+C", () => {
    expect(isBackKey(key("Escape"))).toBe(true);
    expect(isBackKey(key("c", { ctrlKey: true }))).toBe(true);
    expect(isBackKey(key("C", { ctrlKey: true }))).toBe(true);
  });
  it("rejects other keys and modifier combos", () => {
    expect(isBackKey(key("c"))).toBe(false);
    expect(isBackKey(key("c", { ctrlKey: true, shiftKey: true }))).toBe(false);
    expect(isBackKey(key("c", { metaKey: true }))).toBe(false);
    expect(isBackKey(key("Escape", { altKey: true }))).toBe(false);
  });
});

describe("shouldLeaveField", () => {
  const normal = { insertMode: false, visualMode: false, pending: false, exPrompt: false };
  it("leaves only from plain NORMAL", () => {
    expect(shouldLeaveField(normal)).toBe(true);
  });
  it.each([
    ["INSERT", { insertMode: true }],
    ["VISUAL", { visualMode: true }],
    ["pending operator", { pending: true }],
    ["ex prompt", { exPrompt: true }],
  ])("stays in the field in %s", (_name, patch) => {
    expect(shouldLeaveField({ ...normal, ...patch })).toBe(false);
  });
});

describe("snapshotVim", () => {
  it("treats operator, keys, counts and registers as pending", () => {
    expect(snapshotVim({ inputState: { operator: "delete" } }, false).pending).toBe(true);
    expect(snapshotVim({ inputState: { keyBuffer: ["g"] } }, false).pending).toBe(true);
    expect(snapshotVim({ inputState: { prefixRepeat: ["3"] } }, false).pending).toBe(true);
    expect(snapshotVim({ inputState: { registerName: "a" } }, false).pending).toBe(true);
    expect(snapshotVim({ inputState: { keyBuffer: [] } }, false).pending).toBe(false);
  });
  it("is safe on a missing vim state", () => {
    expect(snapshotVim(undefined, false)).toEqual({
      insertMode: false,
      visualMode: false,
      pending: false,
      exPrompt: false,
    });
  });
});
