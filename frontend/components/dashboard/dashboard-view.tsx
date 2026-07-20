"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { browserApiFetch } from "@/lib/api/client";
import { formatDate } from "@/lib/utils/format";
import { AttendanceFineListItem, NextSessionAttendanceEntry, NextSessionInfo, TodoListItem } from "@/types/api";

const FINE_TYPE_LABEL: Record<string, string> = {
  late: "Verspätet",
  absent: "Unentschuldigt",
};

type Props = {
  todos: TodoListItem[];
  fines: AttendanceFineListItem[];
  nextSession: NextSessionInfo;
  canExcuse: boolean;
};

function isTodoDone(todo: TodoListItem): boolean {
  return todo.todo_status_code === "done" || todo.todo_status_code === "cancelled";
}

function isOverdue(dateStr: string | null | undefined): boolean {
  if (!dateStr) return false;
  return new Date(dateStr) < new Date(new Date().toDateString());
}

function sessionCountdownLabel(dateStr: string): string {
  const today = new Date(new Date().toDateString());
  const target = new Date(dateStr);
  const diffDays = Math.round((target.getTime() - today.getTime()) / 86400000);
  if (diffDays === 0) return "Heute";
  if (diffDays === 1) return "Morgen";
  if (diffDays > 1) return `In ${diffDays} Tagen`;
  return "";
}

export function DashboardView({ todos, fines, nextSession, canExcuse }: Props) {
  const router = useRouter();
  const [entries, setEntries] = useState<NextSessionAttendanceEntry[]>(nextSession.entries);
  const [busy, setBusy] = useState<Record<number, boolean>>({});

  const overdueTodos = useMemo(
    () =>
      todos
        .filter((t) => !isTodoDone(t) && isOverdue(t.resolved_due_date))
        .sort((a, b) => (a.resolved_due_date ?? "").localeCompare(b.resolved_due_date ?? ""))
        .slice(0, 8),
    [todos]
  );

  const openFines = useMemo(
    () =>
      fines
        .filter((f) => f.status === "pending")
        .sort((a, b) => (b.protocol_date ?? "").localeCompare(a.protocol_date ?? ""))
        .slice(0, 8),
    [fines]
  );

  const protocol = nextSession.protocol;
  const countdown = protocol ? sessionCountdownLabel(protocol.protocol_date ?? "") : "";

  async function toggleExcused(entry: NextSessionAttendanceEntry) {
    if (!canExcuse || !protocol || busy[entry.participant_id]) return;
    const nextExcused = entry.status !== "excused";
    const previousStatus = entry.status;
    setBusy((b) => ({ ...b, [entry.participant_id]: true }));
    setEntries((current) =>
      current.map((e) => (e.participant_id === entry.participant_id ? { ...e, status: nextExcused ? "excused" : "absent" } : e))
    );
    try {
      await browserApiFetch(`/api/protocols/${protocol.id}/attendance/${entry.participant_id}/excuse`, {
        method: "POST",
        body: JSON.stringify({ excused: nextExcused }),
      });
    } catch {
      setEntries((current) =>
        current.map((e) => (e.participant_id === entry.participant_id ? { ...e, status: previousStatus } : e))
      );
    } finally {
      setBusy((b) => ({ ...b, [entry.participant_id]: false }));
    }
  }

  return (
    <div className="dashboard-grid">
      <section className="panel dashboard-hero">
        <div className="eyebrow">Nächste Sitzung</div>
        {protocol ? (
          <>
            <h1 className="dashboard-hero-title">{protocol.title || protocol.protocol_number}</h1>
            <div className="dashboard-hero-meta">
              <span className="muted">
                {formatDate(protocol.protocol_date)} · {protocol.protocol_number}
              </span>
              {countdown ? <span className="dashboard-countdown-pill pill">{countdown}</span> : null}
            </div>
            <button type="button" className="button-inline dashboard-hero-action" onClick={() => router.push(`/protocols/${protocol.id}`)}>
              Protokoll öffnen
            </button>
          </>
        ) : (
          <>
            <h1 className="dashboard-hero-title">Keine anstehende Sitzung geplant</h1>
            <p className="muted">Sobald ein neues Protokoll angelegt wird, erscheint es hier.</p>
          </>
        )}
      </section>

      <section className="card dashboard-tile dashboard-excuse-card">
        <div className="dashboard-list-header">
          <div className="eyebrow">Teilnehmer entschuldigen</div>
        </div>
        {!protocol ? (
          <p className="muted">Keine nächste Sitzung — daher nichts zu entschuldigen.</p>
        ) : entries.length === 0 ? (
          <p className="muted">Für diese Sitzung ist keine Anwesenheitsliste hinterlegt.</p>
        ) : (
          <div className="excuse-chip-grid">
            {entries.map((entry) => {
              const excused = entry.status === "excused";
              return (
                <button
                  key={entry.participant_id}
                  type="button"
                  className={`excuse-chip${excused ? " excuse-chip-excused" : ""}`}
                  disabled={!canExcuse || busy[entry.participant_id]}
                  title={!canExcuse ? "" : excused ? "Wieder auf unentschuldigt setzen" : "Als entschuldigt markieren"}
                  onClick={() => void toggleExcused(entry)}
                >
                  <span className="excuse-chip-status-icon">{excused ? "✓" : "○"}</span>
                  <span className="excuse-chip-name">{entry.participant_name}</span>
                </button>
              );
            })}
          </div>
        )}
      </section>

      <section className="card dashboard-tile">
        <div className="dashboard-list-header">
          <div className="eyebrow">Überfällige Todos</div>
          <button type="button" className="button-ghost dashboard-list-header-action" onClick={() => router.push("/todos")}>
            Alle
          </button>
        </div>
        {overdueTodos.length === 0 ? (
          <p className="muted">Keine überfälligen Todos.</p>
        ) : (
          <div className="dashboard-list">
            {overdueTodos.map((todo) => (
              <button key={todo.id} type="button" className="dashboard-list-row" onClick={() => todo.protocol_id && router.push(`/protocols/${todo.protocol_id}`)}>
                <span className="dashboard-list-row-icon dashboard-list-row-icon-warn">!</span>
                <span className="dashboard-list-row-text">
                  <span className="dashboard-list-row-title">{todo.task}</span>
                  <span className="dashboard-list-row-sub">
                    {todo.protocol_number ?? ""}
                  </span>
                </span>
                <span className="dashboard-list-row-meta">{todo.resolved_due_date ? formatDate(todo.resolved_due_date) : ""}</span>
              </button>
            ))}
          </div>
        )}
      </section>

      <section className="card dashboard-tile">
        <div className="dashboard-list-header">
          <div className="eyebrow">Offene Bussen</div>
          <button type="button" className="button-ghost dashboard-list-header-action" onClick={() => router.push("/fines")}>
            Alle
          </button>
        </div>
        {openFines.length === 0 ? (
          <p className="muted">Keine offenen Bussen.</p>
        ) : (
          <div className="dashboard-list">
            {openFines.map((fine) => (
              <button key={fine.id} type="button" className="dashboard-list-row" onClick={() => router.push(`/protocols/${fine.protocol_id}`)}>
                <span className="dashboard-list-row-icon dashboard-list-row-icon-fine">CHF</span>
                <span className="dashboard-list-row-text">
                  <span className="dashboard-list-row-title">{fine.participant_name_snapshot}</span>
                  <span className="dashboard-list-row-sub">{FINE_TYPE_LABEL[fine.fine_type] ?? fine.fine_type}</span>
                </span>
                <span className="dashboard-list-row-meta">{fine.amount.toFixed(2)} {fine.currency_label ?? ""}</span>
              </button>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
