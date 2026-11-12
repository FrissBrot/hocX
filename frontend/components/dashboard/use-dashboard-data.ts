"use client";

import { useEffect, useMemo, useState } from "react";
import { useLocale } from "next-intl";

import { effectiveEndDate } from "@/components/events/event-utils";
import { useAllEvents, useAllPages } from "@/components/mobile/mobile-data";
import { isTodoDone, isTodoOverdue, todayIso } from "@/components/mobile/mobile-utils";
import { browserApiFetch } from "@/lib/api/client";
import { fineTotalsByCurrency, formatFineTotals } from "@/lib/utils/fine-stats";
import { formatMoney } from "@/lib/utils/format";
import type { AttendanceFineListItem, FinanceAccount, OpenFinesSummary, SubmissionAssignment, TodoListItem } from "@/types/api";

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
  fineSummary = null,
  permissions,
}: {
  todos: TodoListItem[];
  fines: AttendanceFineListItem[];
  /** Summe der offenen Bussen je Währung vom Server (GET /api/fines/open-summary). */
  fineSummary?: OpenFinesSummary | null;
  permissions: DashboardPermissions;
}) {
  const today = todayIso();
  const locale = useLocale();
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
  // Summe je Währung über ALLE offenen Bussen: bevorzugt serverseitig (die Liste ist nur eine
  // Seite), sonst aus der geladenen Liste. Verschiedene Währungen werden nie addiert.
  const fineTotals = fineSummary
    ? fineSummary.totals.map((total) => ({ currency: total.currency_label, count: total.count, amount: total.amount }))
    : fineTotalsByCurrency(openFines.map((fine) => ({ count: 1, amount: fine.amount, currency: fine.currency_label ?? "" })));
  const fineTotalLabel = formatFineTotals(fineTotals, (amount) => formatMoney(amount, "", locale));
  const fineCount = fineSummary ? fineSummary.count : openFines.length;
  const finePeople = fineSummary ? fineSummary.people : new Set(openFines.map((fine) => fine.participant_id ?? fine.participant_name_snapshot)).size;

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
    fineTotalLabel,
    fineCount,
    finePeople,
    accounts,
    upcomingDeadlines,
  };
}
