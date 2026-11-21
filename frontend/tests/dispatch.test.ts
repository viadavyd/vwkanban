import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { onKeydown, pushMode, topMode, type FieldBridge } from "../src/lib/keys/dispatch";
import type { Action } from "../src/lib/keys/keymap";

// vitest runs in node: the dispatcher only needs these names to exist.
beforeAll(() => {
  const g = globalThis as Record<string, unknown>;
  for (const n of ["HTMLElement", "HTMLInputElement", "HTMLTextAreaElement"]) g[n] ??= class {};
  g.window ??= { getSelection: () => ({ isCollapsed: true }) };
});

function key(k: string, mods: { ctrlKey?: boolean } = {}) {
  const e = {
    key: k,
    ctrlKey: false,
    metaKey: false,
    altKey: false,
    shiftKey: false,
    isComposing: false,
    target: null,
    prevented: false,
    preventDefault() {
      this.prevented = true;
    },
    stopPropagation: vi.fn(),
    ...mods,
  };
  return e;
}

const press = (k: string, mods?: { ctrlKey?: boolean }) => {
  const e = key(k, mods);
  onKeydown(e as unknown as KeyboardEvent);
  return e;
};

let pops: (() => void)[] = [];
afterEach(() => {
  pops.forEach((p) => p());
  pops = [];
});

/** The mode ladder of the board screen: board → card → field, each popping on back. */
function ladder() {
  const log: string[] = [];
  let state: ReturnType<FieldBridge["state"]> = "leave";
  const queued: string[] = [];
  const push = (mode: "board" | "card", next?: () => void) => {
    const pop = pushMode(mode, (a: Action) => {
      log.push(`${mode}:${a}`);
      if (a === "back") pop();
      if ((a === "edit" || a === "open") && next) next();
    });
    pops.push(pop);
  };
  const field = () => {
    const pop = pushMode(
      "field",
      (a) => {
        log.push(`field:${a}`);
        pop();
      },
      { field: { state: () => state, queue: (e) => queued.push(e.key) } },
    );
    pops.push(pop);
  };
  push("board", () => push("card", field));
  return { log, queued, setState: (s: typeof state) => (state = s) };
}

describe("dispatch: the Esc ladder through card and field modes", () => {
  it("goes back exactly one level per press: field → card → board", () => {
    const l = ladder();
    press("i");
    press("i");
    expect(topMode()).toBe("field");
    // vim INSERT / VISUAL / pending operator: Esc and Ctrl+C belong to vim.
    l.setState("stay");
    expect(press("Escape").prevented).toBe(false);
    expect(press("c", { ctrlKey: true }).prevented).toBe(false);
    expect(topMode()).toBe("field");
    // Plain NORMAL: leave the field (only the field), and the key stops here.
    l.setState("leave");
    expect(press("Escape").prevented).toBe(true);
    expect(topMode()).toBe("card");
    press("c", { ctrlKey: true });
    expect(topMode()).toBe("board");
    expect(l.log).toEqual(["board:open", "card:edit", "field:back", "card:back"]);
  });

  it("leaves every other key in a field to vim", () => {
    const l = ladder();
    press("i");
    press("i");
    for (const k of ["j", "i", "d", "u", "?", ":", "Enter", " "]) {
      expect(press(k).prevented, k).toBe(false);
    }
    expect(l.log).toEqual(["board:open", "card:edit"]);
  });

  it("queues every key while the editor is loading, Esc included", () => {
    const l = ladder();
    press("i");
    press("i");
    l.setState("loading");
    for (const k of ["h", "Shift", "i", "Escape"]) press(k);
    expect(l.queued).toEqual(["h", "i", "Escape"]);
    expect(topMode()).toBe("field"); // the replay decides about Esc, not the dispatcher
  });
});
