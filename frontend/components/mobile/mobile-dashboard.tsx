"use client";

import { useRouter } from "next/navigation";
import type { Route } from "next";
import { useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { useAllEvents, useAllPages, useParticipants, useProtocolsByEvent } from "@/components/mobile/mobile-data";
import { EventDetailSheet, EventFormSheet } from "@/components/mobile/mobile-event-sheets";
import { MobileEventRow } from "@/components/mobile/mobile-events";
import { MobileStatsCard } from "@/components/mobile/areas/mobile-statistics";
import { MobileIcon } from "@/components/mobile/mobile-icons";
import { useMobileSession } from "@/components/mobile/mobile-shell";
import { TodoDetailSheet } from "@/components/mobile/mobile-todo-sheets";
import { MobileTodoRow, useTodoToggle } from "@/components/mobile/mobile-todos";
import { MobileAvatar, MobileCard, MobileCardHeader, MobileEmpty, MobileSwitch } from "@/components/mobile/mobile-ui";
import { dateParts, daysBetween, isTodoDone, isTodoOverdue, todayIso } from "@/components/mobile/mobile-utils";
import { effectiveEndDate } from "@/components/events/event-utils";
import { Modal } from "@/components/ui/modal";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { fineTypeLabels } from "@/lib/constants/fine-types";
import { useCycleOptions } from "@/lib/hooks/use-cycle-options";
import { useTagConfig } from "@/lib/hooks/use-tag-config";
import type { AttendanceFineListItem, NextSessionAttendanceEntry, NextSessionInfo, TodoListItem } from "@/types/api";

const DASHBOARD_TODO_LIMIT = 4;
const DASHBOARD_EVENT_LIMIT = 3;
const DASHBOARD_FINE_LIMIT = 5;

export function MobileDashboard({
  todos: initialTodos,
  fines,
  nextSession,
  canExcuse,
  canWrite,
  hasProtocols,
}: {
  todos: TodoListItem[];
  fines: AttendanceFineListItem[];
  nextSession: NextSessionInfo;
  canExcuse: boolean;
  canWrite: boolean;
  hasProtocols: boolean;
}) {
  const t = useTranslations("mobile");
  const tDashboard = useTranslations("dashboard");
  const fineTypeLabel = fineTypeLabels(useTranslations("finances"));
  const locale = useLocale();
  const router = useRouter();
  const showToast = useToast();
  const session = useMobileSession();
  const { tagConfig } = useTagConfig();
  const { options: cycleOptions } = useCycleOptions();
  const [todos, setTodos] = useState<TodoListItem[]>(initialTodos);
  const [mine] = useAllPages<TodoListItem>("/api/todos/my", null);
  const [events, setEvents] = useAllEvents(null);
  const participants = useParticipants(canWrite);
  const protocolsByEvent = useProtocolsByEvent(true);
  const toggleTodo = useTodoToggle(setTodos);
  const [entries, setEntries] = useState<NextSessionAttendanceEntry[]>(nextSession.entries);
  const [excuseOpen, setExcuseOpen] = useState(false);
  const [openTodoId, setOpenTodoId] = useState<string | null>(null);
  const [openEventId, setOpenEventId] = useState<string | null>(null);
  const [editEventId, setEditEventId] = useState<string | null>(null);

  const protocol = nextSession.protocol;
  const today = todayIso();
  const firstName = session?.user?.first_name || session?.user?.display_name || "";
  const tenantName = session?.current_tenant?.name ?? "";

  const myTodos = useMemo(() => {
    const mineIds = new Set(mine.map((todo) => todo.id));
    return todos
      .filter((todo) => !isTodoDone(todo) && (mineIds.has(todo.id) || isTodoOverdue(todo)))
      .sort((a, b) => (a.resolved_due_date ?? "9999").localeCompare(b.resolved_due_date ?? "9999"))
      .slice(0, DASHBOARD_TODO_LIMIT);
  }, [todos, mine]);
  const overdueCount = useMemo(() => todos.filter(isTodoOverdue).length, [todos]);
  const upcoming = useMemo(
    () =>
      events
        .filter((event) => !event.is_cancelled && effectiveEndDate(event).slice(0, 10) >= today)
        .sort((a, b) => a.event_date.localeCompare(b.event_date))
        .slice(0, DASHBOARD_EVENT_LIMIT),
    [events, today]
  );
  const openFines = useMemo(() => fines.filter((fine) => fine.status === "pending"), [fines]);
  const fineTotal = openFines.reduce((sum, fine) => sum + fine.amount, 0);
  const finePeople = new Set(openFines.map((fine) => fine.participant_id ?? fine.participant_name_snapshot)).size;
  const excused = entries.filter((entry) => entry.status === "excused");
  const tagSuggestions = useMemo(() => [...new Set(todos.flatMap((todo) => todo.tags ?? []))], [todos]);

  async function toggleExcused(entry: NextSessionAttendanceEntry) {
    if (!canExcuse || !protocol) return;
    const nextExcused = entry.status !== "excused";
    const setStatus = (status: string) =>
      setEntries((current) => current.map((item) => (item.participant_id === entry.participant_id ? { ...item, status } : item)));
    setStatus(nextExcused ? "excused" : "absent");
    try {
      await browserApiFetch(`/api/protocols/${protocol.id}/attendance/${entry.participant_id}/excuse`, {
        method: "POST",
        body: JSON.stringify({ excused: nextExcused }),
      });
    } catch (error) {
      setStatus(entry.status);
      showToast(error instanceof Error ? error.message : tDashboard("statusChangeFailed"), "error");
    }
  }

  const openTodo = todos.find((todo) => todo.id === openTodoId) ?? null;
  const openEvent = events.find((event) => event.id === openEventId) ?? null;
  const editEvent = events.find((event) => event.id === editEventId) ?? null;

  return (
    <div className="mobile-page mobile-dashboard">
      <div className="mobile-dashboard-top">
        <div className="mobile-dashboard-tenant">
          {session?.current_tenant?.profile_image_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img className="mobile-dashboard-tenant-logo" src={session.current_tenant.profile_image_url} alt="" />
          ) : (
            <span className="mobile-dashboard-tenant-mark">hX</span>
          )}
          <span className="mobile-dashboard-tenant-name">{tenantName}</span>
        </div>
        {session?.user?.display_name ? <MobileAvatar name={session.user.display_name} size="md" /> : null}
      </div>
      <div className="mobile-dashboard-greeting">
        <div className="mobile-muted-sm">{dateParts.weekdayLongDayMonth(today, locale)}</div>
        <h1 className="mobile-page-title">{t("dashboard.greeting", { name: firstName })}</h1>
      </div>

      {!hasProtocols && !protocol ? (
        <MobileEmpty title={tDashboard("emptyTitle")} hint={t("dashboard.emptyHint")} />
      ) : (
        <section className="mobile-hero">
          <div className="mobile-hero-top">
            <span className="mobile-hero-eyebrow">{tDashboard("nextSessionEyebrow")}</span>
            {protocol?.protocol_date && daysBetween(today, protocol.protocol_date) >= 0 ? (
              <span className="mobile-hero-pill">
                {daysBetween(today, protocol.protocol_date) === 0
                  ? t("relative.today")
                  : daysBetween(today, protocol.protocol_date) === 1
                    ? t("relative.tomorrow")
                    : t("relative.inDays", { count: daysBetween(today, protocol.protocol_date) })}
              </span>
            ) : null}
          </div>
          {protocol ? (
            <>
              <div className="mobile-hero-title">{protocol.title || protocol.protocol_number}</div>
              <div className="mobile-hero-meta">
                {protocol.protocol_date ? `${dateParts.long(protocol.protocol_date, locale)} · ` : ""}
                {protocol.protocol_number}
              </div>
              <button type="button" className="mobile-hero-button" onClick={() => router.push(`/protocols/${protocol.id}` as Route)}>
                {t("dashboard.openProtocol")}
              </button>
            </>
          ) : (
            <>
              <div className="mobile-hero-title">{tDashboard("noUpcomingSessionTitle")}</div>
              <div className="mobile-hero-meta">{tDashboard("noUpcomingSessionDescription")}</div>
            </>
          )}
        </section>
      )}

      {protocol && entries.length > 0 ? (
        <button type="button" className="mobile-card mobile-excuse-card" onClick={() => setExcuseOpen(true)}>
          <span className="mobile-excuse-card-text">
            <span className="mobile-eyebrow">{tDashboard("excuseParticipantsEyebrow")}</span>
            <span className="mobile-excuse-card-summary">
              {excused.length > 0
                ? t("dashboard.excuseSummary", { excused: excused.length, expected: entries.length - excused.length })
                : t("dashboard.allExpected", { count: entries.length })}
            </span>
            <span className="mobile-muted-sm mobile-ellipsis">
              {excused.length > 0 ? excused.map((entry) => entry.participant_name).join(", ") : t("dashboard.nobodyExcused")}
            </span>
          </span>
          <span className="mobile-avatar-stack">
            {excused.slice(0, 3).map((entry) => (
              <MobileAvatar key={entry.participant_id} name={entry.participant_name} size="sm" />
            ))}
          </span>
          <MobileIcon name="chevronRight" size={16} strokeWidth={2.2} className="mobile-muted" />
        </button>
      ) : null}

      <MobileCard className="mobile-list-card">
        <MobileCardHeader
          label={t("dashboard.myTodos")}
          badge={overdueCount > 0 ? <span className="mobile-overdue-pill">{t("dashboard.overdue", { count: overdueCount })}</span> : null}
          action={
            <button type="button" className="mobile-text-button" onClick={() => router.push("/todos" as Route)}>
              {tDashboard("allButton")}
            </button>
          }
        />
        {myTodos.length === 0 ? <p className="mobile-card-empty">{t("dashboard.noTodos")}</p> : null}
        {myTodos.map((todo) => (
          <MobileTodoRow
            key={todo.id}
            todo={todo}
            canEdit={canWrite}
            tagConfig={tagConfig}
            showMeta="compact"
            onToggle={() => void toggleTodo(todo)}
            onOpen={() => setOpenTodoId(todo.id)}
          />
        ))}
      </MobileCard>

      <MobileCard className="mobile-list-card">
        <MobileCardHeader
          label={t("dashboard.upcomingEvents")}
          action={
            canWrite ? (
              <button type="button" className="mobile-text-button" onClick={() => router.push("/events" as Route)}>
                {tDashboard("allButton")}
              </button>
            ) : undefined
          }
        />
        {upcoming.length === 0 ? <p className="mobile-card-empty">{t("dashboard.noEvents")}</p> : null}
        {upcoming.map((event) => (
          <MobileEventRow key={event.id} event={event} tagConfig={tagConfig} tile="month" onOpen={() => setOpenEventId(event.id)} />
        ))}
      </MobileCard>

      {openFines.length > 0 ? (
        <MobileCard className="mobile-list-card">
          <div className="mobile-fines-header">
            <div>
              <div className="mobile-eyebrow">{tDashboard("openFinesEyebrow")}</div>
              <div className="mobile-fines-total">
                {openFines[0]?.currency_label ?? ""} {fineTotal.toFixed(2)}
              </div>
            </div>
            <span className="mobile-muted-sm">{t("dashboard.finePeople", { count: finePeople })}</span>
          </div>
          {openFines.slice(0, DASHBOARD_FINE_LIMIT).map((fine) => (
            <div key={fine.id} className="mobile-fine-row">
              <span className="mobile-fine-row-name">{fine.participant_name_snapshot}</span>
              <span className="mobile-muted-sm">{fineTypeLabel[fine.fine_type] ?? fine.fine_type}</span>
              <span className="mobile-fine-row-amount">{fine.amount.toFixed(2)}</span>
            </div>
          ))}
        </MobileCard>
      ) : null}

      <MobileStatsCard />

      {excuseOpen && protocol ? (
        <Modal
          open
          size="sheet"
          title={tDashboard("excuseParticipantsEyebrow")}
          description={[protocol.title || protocol.protocol_number, protocol.protocol_date ? dateParts.dayMonth(protocol.protocol_date, locale) : null].filter(Boolean).join(" · ")}
          onClose={() => setExcuseOpen(false)}
          className="mobile-sheet"
        >
          <div className="mobile-sheet-list">
            {entries.map((entry) => {
              const isExcused = entry.status === "excused";
              return (
                <button
                  key={entry.participant_id}
                  type="button"
                  className="mobile-excuse-row"
                  aria-pressed={isExcused}
                  disabled={!canExcuse}
                  onClick={() => void toggleExcused(entry)}
                >
                  <MobileAvatar name={entry.participant_name} size="md" />
                  <span className="mobile-excuse-row-name">{entry.participant_name}</span>
                  {isExcused ? <span className="mobile-excuse-row-state">{t("dashboard.excused")}</span> : null}
                  <MobileSwitch checked={isExcused} />
                </button>
              );
            })}
          </div>
        </Modal>
      ) : null}

      {openTodo ? (
        <TodoDetailSheet
          todo={openTodo}
          canEdit={canWrite}
          participants={participants}
          tagSuggestions={tagSuggestions}
          tagConfig={tagConfig}
          onClose={() => setOpenTodoId(null)}
          onChange={(next) => setTodos((list) => list.map((item) => (item.id === next.id ? next : item)))}
          onDeleted={(id) => setTodos((list) => list.filter((item) => item.id !== id))}
        />
      ) : null}
      {openEvent && !editEvent ? (
        <EventDetailSheet
          event={openEvent}
          canEdit={canWrite}
          protocol={protocolsByEvent.get(openEvent.id) ?? null}
          participants={participants}
          cycleOptions={cycleOptions}
          tagConfig={tagConfig}
          onClose={() => setOpenEventId(null)}
          onEdit={() => setEditEventId(openEvent.id)}
          onChange={(next) => setEvents((list) => list.map((item) => (item.id === next.id ? next : item)))}
          onDeleted={(id) => setEvents((list) => list.filter((item) => item.id !== id))}
        />
      ) : null}
      {editEvent ? (
        <EventFormSheet
          event={editEvent}
          tags={[...new Set(events.map((event) => event.tag).filter((tag): tag is string => !!tag))]}
          tagConfig={tagConfig}
          onClose={() => setEditEventId(null)}
          onSaved={(saved) => {
            setEvents((list) => list.map((item) => (item.id === saved.id ? saved : item)));
            setEditEventId(null);
          }}
        />
      ) : null}
    </div>
  );
}
