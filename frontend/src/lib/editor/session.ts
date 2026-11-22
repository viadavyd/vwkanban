// One field-editing session in card mode (plan §3.2, §3.4). Pure: no CodeMirror here, so
// it lives in the entry chunk and is unit-tested.
//
// - `base` is the confirmed seq when the field was entered. It is frozen for the session
//   and moves only to the seq of our own ack for this field, so a teammate's save in
//   between is a `conflict` on the server, never a silent overwrite.
// - The draft is never dropped by a remote change: the field only shows
//   `remote changed — :w! keep mine · :e! take theirs`.
// - `:w!` sends the draft with base = the current confirmed seq; `:e!` loads the remote
//   value and resets base to it.

import type { Card } from "../api/boards";
import type { CardFields, TextField } from "../sync/ops";

export const TITLE_MAX = 300;
export const DESCRIPTION_MAX = 20_000;
export const TAG_MAX = 30;
export const TAGS_MAX = 50;

/** Title, tags and due date are single-line fields (`Enter` in INSERT saves and leaves). */
export const SINGLE_LINE: ReadonlySet<TextField> = new Set(["title", "tags", "date"]);

/** A field's value as the editor shows it. */
export function textOf(card: Card, field: TextField): string {
  switch (field) {
    case "title":
      return card.title;
    case "description":
      return card.description;
    case "tags":
      return card.tags.join(" ");
    case "date":
      return card.date ?? "";
  }
}

export type Parsed = { ok: true; fields: CardFields } | { ok: false; error: string };

/** A due date with an optional wall-clock time: `YYYY-MM-DD` or `YYYY-MM-DD HH:MM` (a `T`
 * separator is accepted). Returns the normalised text, or null if invalid. */
export function parseDue(s: string): string | null {
  const m = /^(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}):(\d{2}))?$/.exec(s);
  if (!m) return null;
  const d = new Date(`${m[1]}T00:00:00Z`);
  if (Number.isNaN(d.getTime()) || d.toISOString().slice(0, 10) !== m[1]) return null;
  if (m[2] === undefined) return m[1];
  if (Number(m[2]) > 23 || Number(m[3]) > 59) return null;
  return `${m[1]} ${m[2]}:${m[3]}`;
}

/** Tags are separated by spaces or commas; duplicates are dropped, order is kept. */
export function parseTags(text: string): string[] | string {
  const tags = [...new Set(text.split(/[\s,]+/).filter(Boolean))];
  if (tags.some((t) => t.includes(";"))) return "tags can't contain ';'";
  if (tags.some((t) => t.length > TAG_MAX)) return `a tag is at most ${TAG_MAX} characters`;
  if (tags.length > TAGS_MAX) return `at most ${TAGS_MAX} tags`;
  return tags;
}

/** The card.update fields for a field's text, or why it can't be saved. */
export function parse(field: TextField, text: string): Parsed {
  switch (field) {
    case "title": {
      const title = text.trim();
      if (!title) return { ok: false, error: "the title can't be empty" };
      if (title.length > TITLE_MAX)
        return { ok: false, error: `the title is at most ${TITLE_MAX} characters` };
      return { ok: true, fields: { title } };
    }
    case "description":
      if ([...text].length > DESCRIPTION_MAX)
        return { ok: false, error: `the description is at most ${DESCRIPTION_MAX} characters` };
      return { ok: true, fields: { description: text } };
    case "tags": {
      const tags = parseTags(text);
      return typeof tags === "string" ? { ok: false, error: tags } : { ok: true, fields: { tags } };
    }
    case "date": {
      const raw = text.trim();
      if (!raw) return { ok: true, fields: { date: null } };
      const date = parseDue(raw);
      if (date === null)
        return { ok: false, error: "the due date is YYYY-MM-DD or YYYY-MM-DD HH:MM (or empty)" };
      return { ok: true, fields: { date } };
    }
  }
}

/** What a save sends: the fields and the base_seq. */
export interface Save {
  fields: CardFields;
  baseSeq: number;
}

export class FieldSession {
  /** The text last known to be on the server for this field (at entry, or our last save). */
  saved: string;
  draft: string;
  base: number;
  /** Someone else wrote this field after `base` (seen in an event). */
  remoteChanged = false;
  /** The server refused our save (its message), until `:w!` or `:e!`. */
  conflict: string | null = null;
  /** Why the draft can't be saved (bad date, empty title, ...). */
  error: string | null = null;

  constructor(
    readonly cardId: string,
    readonly field: TextField,
    text: string,
    baseSeq: number,
    private readonly clientId: string,
  ) {
    this.saved = text;
    this.draft = text;
    this.base = baseSeq;
  }

  get dirty(): boolean {
    return this.draft !== this.saved;
  }

  /** The draft needs a choice before it can go out (`:w!` or `:e!`). */
  get needsChoice(): boolean {
    return this.remoteChanged || this.conflict !== null;
  }

  /** The op contents for `:w` / leaving the field, or null when there is nothing to send
   * (unchanged) or it can't be sent (`error` says why). `force` is `:w!`: the base becomes
   * `currentSeq`, so our draft wins over the remote value. */
  save(currentSeq: number, force = false): Save | null {
    const parsed = parse(this.field, this.draft);
    if (!parsed.ok) {
      this.error = parsed.error;
      return null;
    }
    this.error = null;
    if (force) {
      this.base = currentSeq;
      this.remoteChanged = false;
      this.conflict = null;
    } else if (!this.dirty) {
      return null;
    }
    return { fields: parsed.fields, baseSeq: this.base };
  }

  /** Our save of `text` was acked at `seq`: it is the new base. */
  acked(text: string, seq: number): void {
    this.saved = text;
    this.base = Math.max(this.base, seq);
    // The draft might have moved on since; only clear the flags it was sent with.
    if (this.draft === text) {
      this.remoteChanged = false;
      this.conflict = null;
    }
  }

  /** Our save was refused; the draft stays. */
  rejected(message: string): void {
    this.conflict = message;
  }

  /** A confirmed card state arrived (an event or a reject's `current`): flag a newer write
   * of this field by another client. The editor is never touched. */
  observe(card: Card): void {
    const stamp = card.field_meta[this.field];
    if (stamp && stamp.seq > this.base && stamp.client !== this.clientId) {
      if (textOf(card, this.field) === this.draft) {
        // They wrote what we have: nothing to choose.
        this.saved = this.draft;
        this.base = stamp.seq;
        return;
      }
      this.remoteChanged = true;
    }
  }

  /** `:e!`: take the remote value; returns the text for the editor. */
  takeTheirs(card: Card, currentSeq: number): string {
    const text = textOf(card, this.field);
    this.saved = text;
    this.draft = text;
    this.base = currentSeq;
    this.remoteChanged = false;
    this.conflict = null;
    this.error = null;
    return text;
  }
}
