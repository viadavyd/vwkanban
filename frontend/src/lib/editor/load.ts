// The editor chunk is loaded on the first card open only (plan §7: not in the initial
// JS). One promise, so every field shares the download.

type EditorModule = typeof import("./vim");

let chunk: Promise<EditorModule> | null = null;

export function loadEditor(): Promise<EditorModule> {
  chunk ??= import("./vim");
  return chunk;
}
