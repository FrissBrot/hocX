"use client";

import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";

import { dateParts, daysBetween, isTodoOverdue, todayIso } from "@/components/mobile/mobile-utils";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { fineTypeLabels } from "@/lib/constants/fine-types";
import { formatDate } from "@/lib/utils/format";
import { AttendanceFineListItem, NextSessionInfo, TodoListItem } from "@/types/api";

import { DashboardStatsTile } from "./dashboard-stats-tile";
import { DashboardAccess, dashboardPermissions } from "./dashboard-permissions";
import { useDashboardData } from "./use-dashboard-data";
import { useSessionAttendance } from "./use-session-attendance";

type Props = {
  todos: TodoListItem[];
  fines: AttendanceFineListItem[];
  upcomingSessions: NextSessionInfo[];
  access: DashboardAccess;
  hasProtocols: boolean;
  userName?: string;
};

// Gleiche Kacheln wie MobileDashboard, auf dem Desktop mit etwas laengeren Listen.
const TODO_LIMIT = 8;
const EVENT_LIMIT = 5;
const FINE_LIMIT = 8;
const DEADLINE_LIMIT = 5;

type TFunc = (key: string, values?: Record<string, string | number | Date>) => string;

function sessionCountdownLabel(dateStr: string, t: TFunc): string {
  if (!dateStr) return "";
  const diffDays = daysBetween(todayIso(), dateStr.slice(0, 10));
  if (diffDays === 0) return t("today");
  if (diffDays === 1) return t("tomorrow");
  if (diffDays > 1) return t("inDays", { count: diffDays });
  return "";
}

export function DashboardView({ todos, fines, upcomingSessions, access, hasProtocols, userName }: Props) {
  const t = useTranslations("dashboard");
  const locale = useLocale();
  const router = useRouter();
  const fineTypeLabel = fineTypeLabels(useTranslations("finances"));
  const permissions = dashboardPermissions(access);
  const { canExcuse, canWrite, canConfigure } = permissions;
  const { sessions, busy, toggleExcused } = useSessionAttendance(upcomingSessions, canExcuse);
  const data = useDashboardData({ todos, fines, permissions });

  const protocol = sessions[0]?.protocol;
  const countdown = protocol ? sessionCountdownLabel(protocol.protocol_date ?? "", t) : "";

  const header = (
    <div className="page-header dashboard-header">
      <div>
        <p className="muted">{dateParts.weekdayLongDayMonth(data.today, locale)}</p>
        <h1 className="page-title">{userName ? t("greeting", { name: userName }) : t("pageTitle")}</h1>
      </div>
    </div>
  );

  const hero = !hasProtocols && !protocol ? (
    <div className="dashboard-wide">
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
  ) : (
    <section className="panel dashboard-hero">
      {protocol ? <div className="eyebrow">{t("nextSessionEyebrow")}</div> : null}
      {protocol ? (
        <>
          <h2 className="dashboard-hero-title">{protocol.title || protocol.protocol_number}</h2>
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
          <h2 className="dashboard-hero-title">{t("noUpcomingSessionTitle")}</h2>
          <p className="muted">{t("noUpcomingSessionDescription")}</p>
        </>
      )}
    </section>
  );

  return (
    <div className="dashboard-grid">
      {header}
      {hero}

      {sessions.map((session) => session.protocol ? (
        <section key={session.protocol.id} className="card dashboard-tile dashboard-excuse-card">
          <div className="dashboard-list-header">
            <div className="eyebrow">{t("excuseParticipantsEyebrow")}</div>
          </div>
          <div className="grid">
            <strong>{session.protocol.title || session.protocol.protocol_number}</strong>
            <span className="muted">{formatDate(session.protocol.protocol_date)} · {session.protocol.protocol_number}</span>
            {session.entries.length === 0 ? (
              <p className="muted">{t("noAttendanceList")}</p>
            ) : (
              <div className="excuse-chip-grid">
                {session.entries.map((entry) => {
                  const excused = entry.status === "excused";
                  return (
                    <button
                      key={entry.participant_id}
                      type="button"
                      className={`excuse-chip${excused ? " excuse-chip-excused" : ""}`}
                      aria-pressed={excused}
                      disabled={!canExcuse || busy[`${session.protocol!.id}:${entry.participant_id}`]}
                      title={!canExcuse ? "" : excused ? t("unexcuseTitle") : t("excuseTitle")}
                      onClick={() => void toggleExcused(session, entry)}
                    >
                      <span className="excuse-chip-status-icon">{excused ? "✓" : "○"}</span>
                      <span className="excuse-chip-name">{entry.participant_name}</span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </section>
      ) : null)}

      <section className="card dashboard-tile">
        <div className="dashboard-list-header">
          <div className="dashboard-list-header-label">
            <div className="eyebrow">{t("myTodosEyebrow")}</div>
            {data.overdueCount > 0 ? <Badge variant="danger">{t("overdueCount", { count: data.overdueCount })}</Badge> : null}
          </div>
          <button type="button" className="button-ghost dashboard-list-header-action" onClick={() => router.push("/todos")}>
            {t("allButton")}
          </button>
        </div>
        {data.myTodos.length === 0 ? (
          <p className="muted">{t("noOpenTodos")}</p>
        ) : (
          <div className="dashboard-list">
            {data.myTodos.slice(0, TODO_LIMIT).map((todo) => {
              const overdue = isTodoOverdue(todo);
              return (
                <button key={todo.id} type="button" className="dashboard-list-row" onClick={() => router.push(todo.protocol_id ? `/protocols/${todo.protocol_id}` : "/todos")}>
                  <span className={`dashboard-list-row-icon ${overdue ? "dashboard-list-row-icon-warn" : "dashboard-list-row-icon-todo"}`}>{overdue ? "!" : "○"}</span>
                  <span className="dashboard-list-row-text">
                    <span className="dashboard-list-row-title">{todo.task}</span>
                    <span className="dashboard-list-row-sub">{todo.protocol_number ?? ""}</span>
                  </span>
                  <span className={`dashboard-list-row-meta${overdue ? " dashboard-list-row-meta-overdue" : ""}`}>
                    {todo.resolved_due_date ? formatDate(todo.resolved_due_date) : ""}
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </section>

      <section className="card dashboard-tile">
        <div className="dashboard-list-header">
          <div className="eyebrow">{t("upcomingEventsEyebrow")}</div>
          {canWrite ? (
            <button type="button" className="button-ghost dashboard-list-header-action" onClick={() => router.push("/events")}>
              {t("allButton")}
            </button>
          ) : null}
        </div>
        {data.upcomingEvents.length === 0 ? (
          <p className="muted">{t("noUpcomingEvents")}</p>
        ) : (
          <div className="dashboard-list">
            {data.upcomingEvents.slice(0, EVENT_LIMIT).map((event) => {
              const content = (
                <>
                  <span className="dashboard-list-row-icon dashboard-list-row-icon-date">
                    <span className="dashboard-date-day">{dateParts.day(event.event_date)}</span>
                    <span className="dashboard-date-month">{dateParts.monthShort(event.event_date, locale)}</span>
                  </span>
                  <span className="dashboard-list-row-text">
                    <span className="dashboard-list-row-title">{event.title}</span>
                    <span className="dashboard-list-row-sub">{event.location || event.tag || dateParts.weekdayShort(event.event_date, locale)}</span>
                  </span>
                  <span className="dashboard-list-row-meta">{sessionCountdownLabel(event.event_date, t)}</span>
                </>
              );
              // Die Terminverwaltung ist nur fuer Schreibende freigeschaltet - Lesende sehen die Liste ohne Sprung.
              return canWrite ? (
                <button key={event.id} type="button" className="dashboard-list-row" onClick={() => router.push("/events")}>
                  {content}
                </button>
              ) : (
                <div key={event.id} className="dashboard-list-row dashboard-list-row-static">
                  {content}
                </div>
              );
            })}
          </div>
        )}
      </section>

      {permissions.hasFinance ? (
        <section className="card dashboard-tile">
          <div className="dashboard-list-header">
            <div className="eyebrow">{permissions.ownFinesOnly ? t("myOpenFinesEyebrow") : t("openFinesEyebrow")}</div>
            <button type="button" className="button-ghost dashboard-list-header-action" onClick={() => router.push("/fines")}>
              {t("allButton")}
            </button>
          </div>
          {data.openFines.length === 0 ? (
            <p className="muted">{permissions.ownFinesOnly ? t("noOwnOpenFines") : t("noOpenFines")}</p>
          ) : (
            <>
              <div className="dashboard-tile-summary">
                <span className="dashboard-tile-total">
                  {data.fineCurrency} {data.fineTotal.toFixed(2)}
                </span>
                {permissions.ownFinesOnly ? null : <span className="muted">{t("finePeople", { count: data.finePeople })}</span>}
              </div>
              <div className="dashboard-list">
                {data.openFines.slice(0, FINE_LIMIT).map((fine) => (
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
            </>
          )}
        </section>
      ) : null}

      {permissions.showAccounts ? (
        <section className="card dashboard-tile">
          <div className="dashboard-list-header">
            <div className="eyebrow">{t("accountsEyebrow")}</div>
            <button type="button" className="button-ghost dashboard-list-header-action" onClick={() => router.push("/finances")}>
              {t("allButton")}
            </button>
          </div>
          {data.accounts.length === 0 ? (
            <p className="muted">{t("noAccounts")}</p>
          ) : (
            <div className="dashboard-list">
              {data.accounts.map((account) => (
                <button key={account.id} type="button" className="dashboard-list-row" onClick={() => router.push("/finances")}>
                  <span className="dashboard-list-row-text">
                    <span className="dashboard-list-row-title">{account.name}</span>
                    {account.description ? <span className="dashboard-list-row-sub">{account.description}</span> : null}
                  </span>
                  <span className={`dashboard-list-row-meta${account.balance < 0 ? " dashboard-list-row-meta-overdue" : ""}`}>
                    {account.balance.toFixed(2)} {account.currency_label}
                  </span>
                </button>
              ))}
            </div>
          )}
        </section>
      ) : null}

      {permissions.showSubmissions ? (
        <section className="card dashboard-tile">
          <div className="dashboard-list-header">
            <div className="eyebrow">{t("deadlinesEyebrow")}</div>
            <button type="button" className="button-ghost dashboard-list-header-action" onClick={() => router.push("/submission-assignments")}>
              {t("allButton")}
            </button>
          </div>
          {data.upcomingDeadlines.length === 0 ? (
            <p className="muted">{t("noDeadlines")}</p>
          ) : (
            <div className="dashboard-list">
              {data.upcomingDeadlines.slice(0, DEADLINE_LIMIT).map((assignment) => (
                <button key={assignment.id} type="button" className="dashboard-list-row" onClick={() => router.push("/submission-assignments")}>
                  <span className="dashboard-list-row-text">
                    <span className="dashboard-list-row-title">{assignment.title}</span>
                    <span className="dashboard-list-row-sub">{formatDate(assignment.deadline)}</span>
                  </span>
                  <span className="dashboard-list-row-meta">{sessionCountdownLabel(assignment.deadline ?? "", t)}</span>
                </button>
              ))}
            </div>
          )}
        </section>
      ) : null}

      <DashboardStatsTile showFines={permissions.hasFinance} />
    </div>
  );
}
