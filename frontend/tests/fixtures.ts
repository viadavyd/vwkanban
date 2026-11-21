import type { BoardDetail, Card, Status } from "../src/lib/api/boards";

export const TODO: Status = { id: "s-todo", name: "Todo", color: "gray", position: "a0" };
export const DOING: Status = { id: "s-doing", name: "Doing", color: "blue", position: "a1" };

export function card(id: string, position: string, extra: Partial<Card> = {}): Card {
  return {
    id,
    number: Number(id.replace(/\D/g, "")) || 1,
    status_id: TODO.id,
    parent_card_id: null,
    position,
    title: id,
    description: "",
    is_done: false,
    tags: [],
    date: null,
    field_meta: {},
    created_at: "",
    updated_at: "",
    ...extra,
  };
}

export function detail(seq: number, cards: Card[]): BoardDetail {
  return {
    board: { id: "b", title: "B", created_by: "u", created_at: "", updated_at: "" },
    seq,
    statuses: [TODO, DOING],
    cards,
    members: [],
  };
}
