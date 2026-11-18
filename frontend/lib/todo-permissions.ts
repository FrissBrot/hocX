// Einzige Stelle im Frontend, die entscheidet, ob jemand eine Pendenz abhaken bzw. wieder öffnen
// darf (Checkbox in Liste, Board, Kalender und Mobile-Ansicht). Nur Benutzerführung - das Backend
// prüft PATCH /api/protocol-todos/{id} selbst.
//
// meetings.edit darf jede Pendenz abhaken; «eigene Pendenzen erledigen» (todos.complete_own, Plan
// «Berechtigungen» Phase 3) nur die eigenen - ohne beides ist der Zugang read-only. Seit 0108 sind
// Teilnehmende und Konten dieselbe ID, eigene = Konto unter den Zugewiesenen.
// Bewusst ohne "use client": Server Components können es genauso aufrufen.

import { can } from "@/lib/permissions";
import type { SessionInfo, TodoListItem } from "@/types/api";

export type TodoToggleSession = Pick<SessionInfo, "permissions" | "current_tenant" | "user"> | null | undefined;
export type TodoToggleTarget = Pick<TodoListItem, "assigned_user_id" | "assigned_participant_id"> & {
  assigned_participant_ids?: string[];
};

export function isOwnTodo(session: TodoToggleSession, todo: TodoToggleTarget): boolean {
  const me = session?.user?.id != null ? String(session.user.id) : null;
  if (!me) return false;
  return [todo.assigned_user_id, todo.assigned_participant_id, ...(todo.assigned_participant_ids ?? [])].some((id) => id != null && String(id) === me);
}

export function canToggleTodo(session: TodoToggleSession, todo: TodoToggleTarget): boolean {
  return can(session, "meetings.edit") || (can(session, "todos.complete_own") && isOwnTodo(session, todo));
}
