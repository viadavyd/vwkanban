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

export interface BoardDetail {
  board: { id: string; title: string; created_by: string; created_at: string; updated_at: string };
  seq: number;
  statuses: { id: string; name: string; color: string; position: string }[];
  cards: unknown[];
  members: { user_id: string; username: string; role: "owner" | "editor" }[];
}

export const listBoards = () => request<BoardItem[]>("GET", "/boards");

export const createBoard = (title: string) => request<BoardItem>("POST", "/boards", { title });

export const renameBoard = (id: string, title: string) =>
  request<BoardItem>("PATCH", `/boards/${id}`, { title });

export const deleteBoard = (id: string) => request<void>("DELETE", `/boards/${id}`);

export const getBoard = (id: string) => request<BoardDetail>("GET", `/boards/${id}`);
