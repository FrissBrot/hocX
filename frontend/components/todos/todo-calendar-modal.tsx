"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import type { Route } from "next";
import { useLocale, useTranslations } from "next-intl";

import { MobileIcon } from "@/components/mobile/mobile-icons";
import { dateParts, isTodoDone } from "@/components/mobile/mobile-utils";
import { Modal } from "@/components/ui/modal";
import { browserApiFetch } from "@/lib/api/client";
import { CONNECTIONS_HREF } from "@/lib/calendar-feeds";
import { toIntlLocale } from "@/lib/utils/format";
import { formatTimeValue } from "@/lib/utils/time";
import type { EventSummary, TodoListItem } from "@/types/api";
import { addDaysIso, dueInfo, firstName, todoAssignees } from "@/components/todos/todo-overview-utils";

/** Höchstens so viele Einträge je Tag, der Rest als «+N». */
const MAX_PER_DAY = 3;

type Props = {
  open: boolean;
  onClose: () => void;
  todos: TodoListItem[];
  today: string;
  nameById: Map<string, string>;
  /** Pendenz öffnen (schliesst den Kalender vorher, kein Modal im Modal); ohne Recht nicht gesetzt. */
  onOpenTodo?: (todo: TodoListItem) => void;
};

type DayEntry =
  | { type: "event"; key: string; label: string; time: string; tooltip: string }
  | { type: "todo"; key: string; todo: TodoListItem; overdue: boolean; done: boolean; tooltip: string };

function monthStart(iso: string): string {
  return `${iso.slice(0, 7)}-01`;
}

function shiftMonth(iso: string, delta: number): string {
  const [year, month] = iso.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1 + delta, 1));
  return date.toISOString().slice(0, 10);
}

/** Tage des Monatsrasters ab Montag vor dem Ersten, volle Wochen. */
function gridDays(first: string): string[] {
  const [year, month] = first.split("-").map(Number);
  const weekday = (new Date(Date.UTC(year, month - 1, 1)).getUTCDay() + 6) % 7;
  const length = new Date(Date.UTC(year, month, 0)).getUTCDate();
  const total = Math.ceil((weekday + length) / 7) * 7;
  const start = addDaysIso(first, -weekday);
  return Array.from({ length: total }, (_, index) => addDaysIso(start, index));
}

export function TodoCalendarModal({ open, onClose, todos, today, nameById, onOpenTodo }: Props) {
  const t = useTranslations("todos");
  const locale = useLocale();
  const [month, setMonth] = useState(() => monthStart(today));
  const [showTodos, setShowTodos] = useState(true);
  const [showEvents, setShowEvents] = useState(true);
  const [events, setEvents] = useState<EventSummary[] | null>(null);

  useEffect(() => {
    if (!open || !showEvents || events !== null) return;
    let cancelled = false;
    // Best effort: ohne Termine bleibt der Kalender mit den Pendenzen benutzbar
    browserApiFetch<EventSummary[]>("/api/events?limit=500")
      .then((rows) => {
        if (!cancelled) setEvents(rows ?? []);
      })
      .catch(() => {
        if (!cancelled) setEvents([]);
      });
    return () => {
      cancelled = true;
    };
  }, [open, showEvents, events]);

  const weekdays = useMemo(() => {
    const format = new Intl.DateTimeFormat(toIntlLocale(locale), { weekday: "short", timeZone: "UTC" });
    // 2024-01-01 ist ein Montag
    return Array.from({ length: 7 }, (_, index) => format.format(new Date(Date.UTC(2024, 0, 1 + index))).replace(".", ""));
  }, [locale]);

  const days = useMemo(() => gridDays(month), [month]);

  const entriesByDay = useMemo(() => {
    const map = new Map<string, DayEntry[]>();
    const push = (day: string, entry: DayEntry) => {
      const list = map.get(day) ?? [];
      list.push(entry);
      map.set(day, list);
    };
    const first = days[0];
    const last = days[days.length - 1];
    if (showEvents) {
      (events ?? []).forEach((event) => {
        if (event.is_cancelled) return;
        const start = event.event_date.slice(0, 10);
        const end = (event.event_end_date ?? event.event_date).slice(0, 10);
        if (end < first || start > last) return;
        const time = formatTimeValue(event.start_time);
        for (let day = start < first ? first : start; day <= end && day <= last; day = addDaysIso(day, 1)) {
          push(day, { type: "event", key: `e-${event.id}-${day}`, label: event.title, time: day === start ? time : "", tooltip: time ? `${time} ${event.title}` : event.title });
        }
      });
    }
    if (showTodos) {
      todos.forEach((todo) => {
        const info = dueInfo(todo, today);
        if (!info.date || info.date < first || info.date > last) return;
        const people = todoAssignees(todo, nameById).map((person) => person.name).join(", ");
        push(info.date, {
          type: "todo",
          key: `t-${todo.id}`,
          todo,
          overdue: info.tone === "overdue",
          done: isTodoDone(todo),
          tooltip: people ? `${todo.task} · ${people}` : todo.task,
        });
      });
    }
    return map;
  }, [days, events, showEvents, showTodos, todos, today, nameById]);

  const openTodos = todos.filter((todo) => !isTodoDone(todo));
  const overdue = openTodos
    .map((todo) => ({ todo, info: dueInfo(todo, today) }))
    .filter(({ info }) => info.tone === "overdue")
    .sort((a, b) => (a.info.days ?? 0) - (b.info.days ?? 0));
  const undated = openTodos
    .map((todo) => ({ todo, info: dueInfo(todo, today) }))
    .filter(({ info }) => (info.kind === "session" && !info.date) || info.kind === "submission");

  const openTodo = onOpenTodo
    ? (todo: TodoListItem) => {
        onClose();
        onOpenTodo(todo);
      }
    : undefined;

  const header = (
    <div className="todo-calendar-head">
      <h2 className="todo-calendar-month">{dateParts.monthYear(month, locale)}</h2>
      <div className="todo-calendar-nav">
        <button type="button" className="button-icon" aria-label={t("v2.calendarPrev")} onClick={() => setMonth((cur) => shiftMonth(cur, -1))}>
          <MobileIcon name="chevronLeft" size={16} />
        </button>
        <button type="button" className="button-secondary" onClick={() => setMonth(monthStart(today))}>
          {t("v2.calendarToday")}
        </button>
        <button type="button" className="button-icon" aria-label={t("v2.calendarNext")} onClick={() => setMonth((cur) => shiftMonth(cur, 1))}>
          <MobileIcon name="chevronRight" size={16} />
        </button>
      </div>
    </div>
  );

  const toggles = (
    <div className="todo-calendar-toggles">
      <button type="button" className={`button-pill todo-calendar-toggle${showTodos ? " todo-calendar-toggle-on" : ""}`} aria-pressed={showTodos} onClick={() => setShowTodos((v) => !v)}>
        <span className="todo-calendar-swatch todo-calendar-swatch-todo" aria-hidden="true" />
        {t("v2.calendarShowTodos")}
      </button>
      <button type="button" className={`button-pill todo-calendar-toggle${showEvents ? " todo-calendar-toggle-on" : ""}`} aria-pressed={showEvents} onClick={() => setShowEvents((v) => !v)}>
        <span className="todo-calendar-swatch todo-calendar-swatch-event" aria-hidden="true" />
        {t("v2.calendarShowEvents")}
      </button>
    </div>
  );

  return (
    <Modal open={open} onClose={onClose} title={t("v2.calendarTitle")} size="fullscreen" header={header} headerActions={toggles} className="todo-calendar-modal">
      <div className="todo-calendar">
        <div className="todo-calendar-grid" role="grid" aria-label={dateParts.monthYear(month, locale)}>
          <div className="todo-calendar-row todo-calendar-weekdays" role="row">
            {weekdays.map((name) => (
              <div key={name} className="todo-calendar-weekday" role="columnheader">
                {name}
              </div>
            ))}
          </div>
          {Array.from({ length: days.length / 7 }, (_, week) => (
            <div key={week} className="todo-calendar-row" role="row">
              {days.slice(week * 7, week * 7 + 7).map((day, column) => {
                const entries = entriesByDay.get(day) ?? [];
                const outside = day.slice(0, 7) !== month.slice(0, 7);
                const classes = [
                  "todo-calendar-day",
                  column >= 5 ? "todo-calendar-day-weekend" : "",
                  outside ? "todo-calendar-day-outside" : "",
                  day === today ? "todo-calendar-day-today" : "",
                ].filter(Boolean).join(" ");
                return (
                  <div key={day} className={classes} role="gridcell" aria-label={dateParts.long(day, locale)}>
                    <span className="todo-calendar-day-number">{dateParts.day(day)}</span>
                    {entries.slice(0, MAX_PER_DAY).map((entry) =>
                      entry.type === "event" ? (
                        <span key={entry.key} className="todo-calendar-entry todo-calendar-entry-event" title={entry.tooltip}>
                          {entry.time ? <span className="todo-calendar-entry-time">{entry.time}</span> : null}
                          <span className="todo-calendar-entry-label">{entry.label}</span>
                        </span>
                      ) : (
                        <CalendarTodoEntry key={entry.key} entry={entry} onOpen={openTodo} />
                      )
                    )}
                    {entries.length > MAX_PER_DAY ? (
                      <span className="todo-calendar-more" title={entries.slice(MAX_PER_DAY).map((entry) => entry.tooltip).join("\n")}>
                        {t("v2.calendarMore", { count: entries.length - MAX_PER_DAY })}
                      </span>
                    ) : null}
                  </div>
                );
              })}
            </div>
          ))}
        </div>

        <aside className="todo-calendar-side">
          <section className="todo-calendar-side-section">
            <h3 className="todo-calendar-side-title todo-v2-tone-overdue">{t("v2.groupOverdue")}</h3>
            {overdue.length === 0 ? <p className="muted todo-calendar-side-empty">{t("v2.calendarNoneOverdue")}</p> : null}
            {overdue.map(({ todo, info }) => (
              <SideCard key={todo.id} todo={todo} sub={t("v2.overdueSinceDays", { count: -(info.days ?? 0) })} tone="overdue" onOpen={openTodo} />
            ))}
          </section>
          <section className="todo-calendar-side-section">
            <h3 className="todo-calendar-side-title">{t("v2.calendarUndated")}</h3>
            {undated.length === 0 ? <p className="muted todo-calendar-side-empty">{t("v2.calendarNoneUndated")}</p> : null}
            {undated.map(({ todo, info }) => {
              const names = todoAssignees(todo, nameById).map((person) => firstName(person.name)).join(", ");
              const kind = info.kind === "session" ? t("v2.dueNextSession") : t("v2.dueWithSubmission");
              return <SideCard key={todo.id} todo={todo} sub={names ? t("v2.calendarUndatedWithNames", { kind, names }) : kind} tone="normal" onOpen={openTodo} />;
            })}
          </section>
          <div className="todo-calendar-legend">
            <span><span className="todo-calendar-swatch todo-calendar-swatch-todo" aria-hidden="true" />{t("v2.legendTodo")}</span>
            <span><span className="todo-calendar-swatch todo-calendar-swatch-overdue" aria-hidden="true" />{t("v2.legendOverdue")}</span>
            <span><span className="todo-calendar-swatch todo-calendar-swatch-event" aria-hidden="true" />{t("v2.legendEvent")}</span>
          </div>
          <Link href={CONNECTIONS_HREF as Route} className="todo-calendar-subscribe">
            {t("v2.calendarSubscribe")}
            <MobileIcon name="chevronRight" size={12} strokeWidth={2.4} />
          </Link>
        </aside>
      </div>
    </Modal>
  );
}

function CalendarTodoEntry({ entry, onOpen }: { entry: Extract<DayEntry, { type: "todo" }>; onOpen?: (todo: TodoListItem) => void }) {
  const className = `todo-calendar-entry todo-calendar-entry-todo${entry.overdue ? " todo-calendar-entry-overdue" : ""}${entry.done ? " todo-calendar-entry-done" : ""}`;
  const content = (
    <>
      <span className="todo-calendar-swatch todo-calendar-swatch-inline" aria-hidden="true" />
      <span className="todo-calendar-entry-label">{entry.todo.task}</span>
    </>
  );
  if (!onOpen) {
    return (
      <span className={className} title={entry.tooltip}>
        {content}
      </span>
    );
  }
  return (
    <button type="button" className={className} title={entry.tooltip} onClick={() => onOpen(entry.todo)}>
      {content}
    </button>
  );
}

function SideCard({ todo, sub, tone, onOpen }: { todo: TodoListItem; sub: string; tone: "overdue" | "normal"; onOpen?: (todo: TodoListItem) => void }) {
  const body = (
    <>
      <span className="todo-calendar-side-card-title">{todo.task}</span>
      <span className={`todo-calendar-side-card-sub todo-v2-tone-${tone}`}>{sub}</span>
    </>
  );
  return onOpen ? (
    <button type="button" className="todo-calendar-side-card" onClick={() => onOpen(todo)}>
      {body}
    </button>
  ) : (
    <div className="todo-calendar-side-card">{body}</div>
  );
}
