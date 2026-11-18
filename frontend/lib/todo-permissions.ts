// Einzige Stelle im Frontend, die entscheidet, ob jemand eine Pendenz abhaken bzw. wieder öffnen
// darf (Checkbox in Liste, Board, Kalender und Mobile-Ansicht). Nur Benutzerführung - das Backend
// prüft PATCH /api/protocol-todos/{id} selbst.
//
// Heute: meetings.edit. Geplant ist ein zusätzliches Recht «eigene Pendenzen erledigen»
// (vermutlich todos.complete_own): beim Zusammenführen hier einhängen, z. B.
//   can(session, "meetings.edit") || (can(session, "todos.complete_own") && isOwnTodo(session, todo))
// Bewusst ohne "use client": Server Components können es genauso aufrufen.

import { can } from "@/lib/permissions";
import type { SessionInfo, TodoListItem } from "@/types/api";

export type TodoToggleSession = Pick<SessionInfo, "permissions" | "current_tenant" | "user"> | null | undefined;
export type TodoToggleTarget = Pick<TodoListItem, "assigned_user_id" | "assigned_participant_id"> & {
  assigned_participant_ids?: string[];
};

export function canToggleTodo(session: TodoToggleSession, todo: TodoToggleTarget): boolean {
  void todo; // für das künftige Recht auf eigene Pendenzen (siehe oben)
  return can(session, "meetings.edit");
}
