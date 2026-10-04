"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { EmptyState } from "@/components/ui/empty-state";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { fineTypeLabels } from "@/lib/constants/fine-types";
import { formatDate } from "@/lib/utils/format";
import { AttendanceFineListItem, NextSessionAttendanceEntry, NextSessionInfo, TodoListItem } from "@/types/api";

type Props = {
  todos: TodoListItem[];
  fines: AttendanceFineListItem[];
  nextSession: NextSessionInfo;
  canExcuse: boolean;
  canWrite: boolean;
  hasProtocols: boolean;
  canConfigure: boolean;
};

function isTodoDone(todo: TodoListItem): boolean {
  return todo.todo_status_code === "done" || todo.todo_status_code === "cancelled";
}

function isOverdue(dateStr: string | null | undefined): boolean {
  if (!dateStr) return false;
  return new Date(dateStr) < new Date(new Date().toDateString());
}

type TFunc = (key: string, values?: Record<string, string | number | Date>) => string;

function sessionCountdownLabel(dateStr: string, t: TFunc): string {
  const today = new Date(new Date().toDateString());
  const target = new Date(dateStr);
  const diffDays = Math.round((target.getTime() - today.getTime()) / 86400000);
  if (diffDays === 0) return t("today");
  if (diffDays === 1) return t("tomorrow");
  if (diffDays > 1) return t("inDays", { count: diffDays });
  return "";
}

export function DashboardView({ todos, fines, nextSession, canExcuse, canWrite, hasProtocols, canConfigure }: Props) {
  const t = useTranslations("dashboard");
  const router = useRouter();
  const showToast = useToast();
  const fineTypeLabel = fineTypeLabels(useTranslations("finances"));
  const [entries, setEntries] = useState<NextSessionAttendanceEntry[]>(nextSession.entries);
  const [busy, setBusy] = useState<Record<string, boolean>>({});

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
  const countdown = protocol ? sessionCountdownLabel(protocol.protocol_date ?? "", t) : "";

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
    } catch (err: unknown) {
      setEntries((current) =>
        current.map((e) => (e.participant_id === entry.participant_id ? { ...e, status: previousStatus } : e))
      );
      // The optimistic status flip was already reverted above - without this, that revert
      // was the only visible feedback, so a real failure just looked like the click didn't
      // register (audit F8, 2026-08-16).
      showToast(err instanceof Error ? err.message : t("statusChangeFailed"), "error");
    } finally {
      setBusy((b) => ({ ...b, [entry.participant_id]: false }));
    }
  }

  if (!hasProtocols && !protocol) {
    return (
      <div className="grid">
        <div className="page-header">
          <div>
            <h1 className="page-title">{t("pageTitle")}</h1>
            <p className="muted">{t("pageIntro")}</p>
          </div>
        </div>
        <EmptyState
          title={t("emptyTitle")}
          description={t("emptyDescription")}
          actions={
            canWrite || canConfigure ? (
              <>
                {canWrite ? (
                  <button type="button" className="button-primary" onClick={() => router.push("/protocols?create=1")}>
                    {t("newProtocolButton")}
                  </button>
                ) : null}
                {canConfigure ? (
                  <button type="button" className={canWrite ? "button-secondary" : "button-primary"} onClick={() => router.push("/templates")}>
                    {t("setupTemplateButton")}
                  </button>
                ) : null}
              </>
            ) : null
          }
          hint={t("emptyHint")}
        />
      </div>
    );
  }

  return (
    <div className="dashboard-grid">
      <section className="panel dashboard-hero">
        <div className="eyebrow">{t("nextSessionEyebrow")}</div>
        {protocol ? (
          <>
            <h1 className="dashboard-hero-title">{protocol.title || protocol.protocol_number}</h1>
            <div className="dashboard-hero-meta">
              <span className="muted">
                {formatDate(protocol.protocol_date)} · {protocol.protocol_number}
              </span>
              {countdown ? <span className="dashboard-countdown-pill pill">{countdown}</span> : null}
            </div>
            <button type="button" className="button-secondary dashboard-hero-action" onClick={() => router.push(`/protocols/${protocol.id}`)}>
              {t("openProtocolButton")}
            </button>
          </>
        ) : (
          <>
            <h1 className="dashboard-hero-title">{t("noUpcomingSessionTitle")}</h1>
            <p className="muted">{t("noUpcomingSessionDescription")}</p>
          </>
        )}
      </section>

      <section className="card dashboard-tile dashboard-excuse-card">
        <div className="dashboard-list-header">
          <div className="eyebrow">{t("excuseParticipantsEyebrow")}</div>
        </div>
        {!protocol ? (
          <p className="muted">{t("noSessionForExcuse")}</p>
        ) : entries.length === 0 ? (
          <p className="muted">{t("noAttendanceList")}</p>
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
                  title={!canExcuse ? "" : excused ? t("unexcuseTitle") : t("excuseTitle")}
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
          <div className="eyebrow">{t("overdueTodosEyebrow")}</div>
          <button type="button" className="button-ghost dashboard-list-header-action" onClick={() => router.push("/todos")}>
            {t("allButton")}
          </button>
        </div>
        {overdueTodos.length === 0 ? (
          <p className="muted">{t("noOverdueTodos")}</p>
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
                <span className="dashboard-list-row-meta dashboard-list-row-meta-overdue">
                  {todo.resolved_due_date ? formatDate(todo.resolved_due_date) : ""}
                </span>
              </button>
            ))}
          </div>
        )}
      </section>

      <section className="card dashboard-tile">
        <div className="dashboard-list-header">
          <div className="eyebrow">{t("openFinesEyebrow")}</div>
          <button type="button" className="button-ghost dashboard-list-header-action" onClick={() => router.push("/fines")}>
            {t("allButton")}
          </button>
        </div>
        {openFines.length === 0 ? (
          <p className="muted">{t("noOpenFines")}</p>
        ) : (
          <div className="dashboard-list">
            {openFines.map((fine) => (
              <button key={fine.id} type="button" className="dashboard-list-row" onClick={() => router.push(`/protocols/${fine.protocol_id}`)}>
                <span className="dashboard-list-row-icon dashboard-list-row-icon-fine">CHF</span>
                <span className="dashboard-list-row-text">
                  <span className="dashboard-list-row-title">{fine.participant_name_snapshot}</span>
                  <span className="dashboard-list-row-sub">{fineTypeLabel[fine.fine_type] ?? fine.fine_type}</span>
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
