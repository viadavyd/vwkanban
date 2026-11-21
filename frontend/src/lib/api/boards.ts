import { request, requestRaw } from "./client";

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

export interface Member {
  user_id: string;
  username: string;
  role: "owner" | "editor";
}

export const listMembers = (boardId: string) =>
  request<Member[]>("GET", `/boards/${boardId}/members`);

/** Adds a user as an editor (owner only). */
export const addMember = (boardId: string, username: string) =>
  request<Member>("POST", `/boards/${boardId}/members`, { username });

/** Removes a member (owner only); their open sockets on the board are closed. */
export const removeMember = (boardId: string, userId: string) =>
  request<void>("DELETE", `/boards/${boardId}/members/${userId}`);

// --- CSV (plan §3.1, §3.6) ------------------------------------------------------------

/** The server refuses larger files; checked here first so nothing is uploaded. */
export const CSV_MAX_BYTES = 5 * 1024 * 1024;

/** The export download (`E`): a plain GET, so the browser saves it with its filename. */
export const exportUrl = (boardId: string) => `/api/boards/${boardId}/export.csv`;

export interface ImportResult {
  created: number;
  /** names of the columns the import adds */
  statuses_created: string[];
  /** "kept": the CSV ids are the card numbers; else every card gets a new one */
  numbers: "kept" | "renumbered";
  warnings: string[];
  /** the board.import event's seq; null on a dry run */
  seq: number | null;
}

/** One bad row of a refused import (ApiError.details.rows). */
export interface ImportRowError {
  row: number;
  message: string;
}

/** Imports a CSV file (`I`). `dryRun` validates and counts without writing (the preview).
 * A refused file is an ApiError with `details.rows`. */
export const importCsv = (boardId: string, file: Blob, clientId: string, dryRun: boolean) => {
  const q = new URLSearchParams({ client_id: clientId });
  if (dryRun) q.set("dry_run", "1");
  return requestRaw<ImportResult>("POST", `/boards/${boardId}/import?${q}`, file, "text/csv");
};
