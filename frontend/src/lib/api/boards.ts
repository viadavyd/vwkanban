import { request } from "./client";

export interface StatusCount {
  name: string;
  color: string;
  count: number;
}

export interface BoardItem {
  id: string;
  title: string;
  updated_at: string;
  role: "owner" | "editor";
  summary: { total: number; done: number; by_status: StatusCount[] };
}

export interface Status {
  id: string;
  name: string;
  color: string;
  /** Fractional key, computed by the server only; "" while unconfirmed. */
  position: string;
  field_meta?: Record<string, FieldStamp>;
}

export interface FieldStamp {
  seq: number;
  client: string;
}

export interface Card {
  id: string;
  /** Board-local number (#12); 0 while an optimistic create is unconfirmed. */
  number: number;
  status_id: string | null;
  parent_card_id: string | null;
  /** Fractional key, computed by the server only; "" while unconfirmed. */
  position: string;
  title: string;
  description: string;
  is_done: boolean;
  tags: string[];
  /** Due date, YYYY-MM-DD. */
  date: string | null;
  field_meta: Record<string, FieldStamp>;
  created_at: string;
  updated_at: string;
}

export interface BoardDetail {
  board: { id: string; title: string; created_by: string; created_at: string; updated_at: string };
  seq: number;
  statuses: Status[];
  cards: Card[];
  members: { user_id: string; username: string; role: "owner" | "editor" }[];
}

export const listBoards = () => request<BoardItem[]>("GET", "/boards");

export const createBoard = (title: string) => request<BoardItem>("POST", "/boards", { title });

export const renameBoard = (id: string, title: string) =>
  request<BoardItem>("PATCH", `/boards/${id}`, { title });

export const deleteBoard = (id: string) => request<void>("DELETE", `/boards/${id}`);

export const getBoard = (id: string) => request<BoardDetail>("GET", `/boards/${id}`);
