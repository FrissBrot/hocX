"use client";

import { useEffect, useMemo, useState } from "react";

import { effectiveEndDate } from "@/components/events/event-utils";
import { useAllEvents, useAllPages } from "@/components/mobile/mobile-data";
import { isTodoDone, isTodoOverdue, todayIso } from "@/components/mobile/mobile-utils";
import { browserApiFetch } from "@/lib/api/client";
import type { AttendanceFineListItem, FinanceAccount, SubmissionAssignment, TodoListItem } from "@/types/api";

import type { DashboardPermissions } from "./dashboard-permissions";

// Gemeinsame Datengrundlage fuer Desktop- und Mobile-Dashboard: beide Ansichten zeigen
// dieselben Kacheln, nur unterschiedlich dargestellt. Welche Kachel eine Rolle sieht, steht in
// dashboard-permissions.ts.

function useOptionalFetch<T>(path: string, enabled: boolean): T[] {
  const [items, setItems] = useState<T[]>([]);
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    browserApiFetch<T[]>(path)
      .then((list) => {
        if (!cancelled && Array.isArray(list)) setItems(list);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [path, enabled]);
  return items;
}

export function useDashboardData({
  todos: initialTodos,
  fines,
  permissions,
}: {
  todos: TodoListItem[];
  fines: AttendanceFineListItem[];
  permissions: DashboardPermissions;
}) {
  const today = todayIso();
  const [todos, setTodos] = useState<TodoListItem[]>(initialTodos);
  const [mine] = useAllPages<TodoListItem>("/api/todos/my", null);
  const [events, setEvents] = useAllEvents(null);
  const accounts = useOptionalFetch<FinanceAccount>("/api/finance/accounts", permissions.showAccounts);
  const assignments = useOptionalFetch<SubmissionAssignment>("/api/submission-assignments", permissions.showSubmissions);

  // Eigene offene Todos plus alle ueberfaelligen, die naechste Faelligkeit zuerst.
  const myTodos = useMemo(() => {
    const mineIds = new Set(mine.map((todo) => todo.id));
    return todos
      .filter((todo) => !isTodoDone(todo) && (mineIds.has(todo.id) || isTodoOverdue(todo)))
      .sort((a, b) => (a.resolved_due_date ?? "9999").localeCompare(b.resolved_due_date ?? "9999"));
  }, [todos, mine]);
  const overdueCount = useMemo(() => todos.filter(isTodoOverdue).length, [todos]);

  const upcomingEvents = useMemo(
    () =>
      events
        .filter((event) => !event.is_cancelled && effectiveEndDate(event).slice(0, 10) >= today)
        .sort((a, b) => a.event_date.localeCompare(b.event_date)),
    [events, today]
  );

  const openFines = useMemo(
    () => fines.filter((fine) => fine.status === "pending").sort((a, b) => (b.protocol_date ?? "").localeCompare(a.protocol_date ?? "")),
    [fines]
  );
  const fineTotal = openFines.reduce((sum, fine) => sum + fine.amount, 0);
  const fineCurrency = openFines[0]?.currency_label ?? "";
  const finePeople = new Set(openFines.map((fine) => fine.participant_id ?? fine.participant_name_snapshot)).size;

  // Abgaben, deren Frist noch bevorsteht - die naechste zuerst.
  const upcomingDeadlines = useMemo(
    () =>
      assignments
        .filter((assignment) => assignment.deadline && assignment.deadline.slice(0, 10) >= today)
        .sort((a, b) => (a.deadline ?? "").localeCompare(b.deadline ?? "")),
    [assignments, today]
  );

  return {
    today,
    todos,
    setTodos,
    events,
    setEvents,
    myTodos,
    overdueCount,
    upcomingEvents,
    openFines,
    fineTotal,
    fineCurrency,
    finePeople,
    accounts,
    upcomingDeadlines,
  };
}
