// The board register (plan §4.3): one unnamed register per tab. `y` and `d` put a snapshot
// of the card and its children in it (a copy); `x` marks a card to move instead. `p` pastes
// a copy as new cards (new ids; the server assigns numbers) or moves the marked card. The
// system clipboard is not used in the MVP.

import type { Card } from "../api/boards";
import { uuid7 } from "../ids";
import { createCard, type ChildData, type Op } from "./ops";

/** A card's content without identity: what a paste recreates. */
export type Snapshot = Required<Omit<ChildData, "id">> & {
  children: Required<Omit<ChildData, "id">>[];
};

export type Register = { kind: "copy"; snapshot: Snapshot } | { kind: "move"; id: string } | null;

const content = (c: Card) => ({
  title: c.title,
  description: c.description,
  tags: [...c.tags],
  date: c.date,
  is_done: c.is_done,
});

export function snapshot(card: Card, children: readonly Card[]): Snapshot {
  return { ...content(card), children: children.map(content) };
}

/** The op that pastes `snap` into a column, below `afterId` (or at the end). */
export function pasteOp(seq: number, snap: Snapshot, statusId: string, afterId?: string): Op {
  const { children, ...card } = snap;
  return createCard(seq, {
    status_id: statusId,
    ...(afterId && { after_id: afterId }),
    ...card,
    ...(children.length && { children: children.map((c) => ({ id: uuid7(), ...c })) }),
  });
}
