"use client";

import Link from "next/link";
import type { Route } from "next";
import { useMemo, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";

import { useProtocolsByEvent } from "@/components/mobile/mobile-data";
import { dateParts, daysBetween, isTodoOverdue, todayIso } from "@/components/mobile/mobile-utils";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { fineTypeLabels } from "@/lib/constants/fine-types";
import { formatDate, formatMoney } from "@/lib/utils/format";
import type { AttendanceFineListItem, NextSessionAttendanceEntry, NextSessionInfo, OpenFinesSummary, TodoListItem } from "@/types/api";

import { groupAgenda, type AgendaItem, type AgendaKind } from "./dashboard-agenda";
import { DashboardHeaderKpis } from "./dashboard-header-kpis";
import { DashboardAccess, dashboardPermissions } from "./dashboard-permissions";
import { useDashboardData } from "./use-dashboard-data";
import { useSessionAttendance } from "./use-session-attendance";

type Props = {
  todos: TodoListItem[];
  fines: AttendanceFineListItem[];
  /** Offene Bussen je Währung (Server-Summe über alle, nicht nur die geladene Seite). */
  fineSummary?: OpenFinesSummary | null;
  upcomingSessions: NextSessionInfo[];
  access: DashboardAccess;
  hasProtocols: boolean;
  userName?: string;
};

// Dashboard v2: links die nächste Sitzung mit Anwesenheit und die Agenda, rechts Pendenzen,
// Bussen und Kontostände. Gleiche Datengrundlage wie MobileDashboard (use-dashboard-data.ts).
const TODO_LIMIT = 6;
const AGENDA_LIMIT = 8;
const FINE_LIMIT = 5;

type TFunc = (key: string, values?: Record<string, string | number | Date>) => string;

function countdownLabel(dateStr: string, t: TFunc): string {
  if (!dateStr) return "";
  const diffDays = daysBetween(todayIso(), dateStr.slice(0, 10));
  if (diffDays === 0) return t("today");
  if (diffDays === 1) return t("tomorrow");
  if (diffDays > 1) return t("inDays", { count: diffDays });
  return "";
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

const KIND_BADGE: Record<AgendaKind, "info" | "neutral" | "warning"> = { session: "info", event: "neutral", deadline: "warning" };

/** Personen der Sitzung zum Entschuldigen; im Hero (dunkel) oder als eigene Karte. */
function ExcuseChips({
  session,
  canExcuse,
  busy,
  onToggle,
  variant,
}: {
  session: NextSessionInfo;
  canExcuse: boolean;
  busy: Record<string, boolean>;
  onToggle: (session: NextSessionInfo, entry: NextSessionAttendanceEntry) => void;
  variant: "hero" | "card";
}) {
  const t = useTranslations("dashboard");
  const protocol = session.protocol!;
  const excused = session.entries.filter((entry) => entry.status === "excused").length;
  if (session.entries.length === 0) return <p className="dashboard-excuse-hint">{t("noAttendanceList")}</p>;
  return (
    <>
      <div className="dashboard-excuse-head">
        <div className="dashboard-eyebrow">{t("attendanceEyebrow")}</div>
        <div className="dashboard-excuse-counts">
          <span>{t("expectedCount", { count: session.entries.length - excused })}</span>
          <span className="dashboard-excuse-count-excused">{t("excusedCount", { count: excused })}</span>
        </div>
      </div>
      <div className={`excuse-chip-grid excuse-chip-grid-${variant}`}>
        {session.entries.map((entry) => {
          const isExcused = entry.status === "excused";
          return (
            <button
              key={entry.participant_id}
              type="button"
              className={`excuse-chip${isExcused ? " excuse-chip-excused" : ""}`}
              aria-pressed={isExcused}
              disabled={!canExcuse || busy[`${protocol.id}:${entry.participant_id}`]}
              title={!canExcuse ? t("excuseNoPermission") : isExcused ? t("unexcuseTitle") : t("excuseTitle")}
              onClick={() => onToggle(session, entry)}
            >
              <span className="excuse-chip-status-icon" aria-hidden="true">{isExcused ? "✓" : initials(entry.participant_name)}</span>
              <span className="excuse-chip-name">{entry.participant_name}</span>
            </button>
          );
        })}
      </div>
      {/* U7: gesperrte Chips ohne Recht sichtbar begründen statt still nichts zu tun. */}
      <p className="dashboard-excuse-hint">{canExcuse ? t("excuseHint") : t("excuseNoPermission")}</p>
    </>
  );
}

function CardHeader({ title, badge, href, linkLabel }: { title: string; badge?: ReactNode; href?: string; linkLabel?: string }) {
  return (
    <div className="dashboard-card-header">
      <div className="dashboard-card-header-label">
        <h2 className="dashboard-eyebrow">{title}</h2>
        {badge}
      </div>
      {href && linkLabel ? (
        <Link href={href as Route} className="dashboard-card-link">
          {linkLabel}
          <span aria-hidden="true">→</span>
        </Link>
      ) : null}
    </div>
  );
}

export function DashboardView({ todos, fines, fineSummary = null, upcomingSessions, access, hasProtocols, userName }: Props) {
  const t = useTranslations("dashboard");
  const locale = useLocale();
  const router = useRouter();
  const fineTypeLabel = fineTypeLabels(useTranslations("finances"));
  const permissions = dashboardPermissions(access);
  const { canExcuse, canWrite, canConfigure } = permissions;
  const { sessions, busy, toggleExcused } = useSessionAttendance(upcomingSessions, canExcuse);
  const data = useDashboardData({ todos, fines, fineSummary, permissions });
  const protocolsByEvent = useProtocolsByEvent(true);

  const [firstSession, ...otherSessions] = sessions.filter((session) => session.protocol);
  const protocol = firstSession?.protocol;
  const countdown = protocol ? countdownLabel(protocol.protocol_date ?? "", t) : "";
  const year = Number(data.today.slice(0, 4));

  const agenda = useMemo(() => {
    const items: AgendaItem[] = data.upcomingEvents.map((event) => {
      const session = protocolsByEvent.get(event.id);
      return {
        id: `event:${event.id}`,
        date: event.event_date,
        title: event.title,
        sub: [event.location || event.tag || "", session?.protocol_number ?? ""].filter(Boolean).join(" · "),
        kind: session ? "session" : "event",
        // Die Terminverwaltung ist nur für Schreibende freigeschaltet - Lesende sehen die Liste ohne Sprung.
        href: session ? `/protocols/${session.id}` : canWrite ? "/events" : null,
      };
    });
    if (permissions.showSubmissions) {
      for (const assignment of data.upcomingDeadlines) {
        items.push({ id: `deadline:${assignment.id}`, date: assignment.deadline ?? "", title: assignment.title, sub: t("deadlineSub"), kind: "deadline", href: "/submission-assignments" });
      }
    }
    return groupAgenda(items, data.today, AGENDA_LIMIT);
  }, [data.upcomingEvents, data.upcomingDeadlines, data.today, protocolsByEvent, permissions.showSubmissions, canWrite, t]);

  const header = (
    <div className="dashboard-header">
      <div>
        <p className="dashboard-date">{dateParts.weekdayLongDayMonth(data.today, locale)}</p>
        <h1 className="page-title dashboard-title">{userName ? t("greeting", { name: userName }) : t("pageTitle")}</h1>
      </div>
      <DashboardHeaderKpis year={year} fineTotalLabel={data.fineTotalLabel} showFines={permissions.hasFinance} />
    </div>
  );

  const hero = !hasProtocols && !protocol ? (
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
  ) : (
    <section className="dashboard-hero">
      <div className="dashboard-hero-main">
        {protocol?.protocol_date ? (
          <div className="dashboard-hero-date" aria-hidden="true">
            <span className="dashboard-hero-date-month">{dateParts.monthShort(protocol.protocol_date, locale)}</span>
            <span className="dashboard-hero-date-day">{dateParts.day(protocol.protocol_date)}</span>
            <span className="dashboard-hero-date-weekday">{dateParts.weekdayShort(protocol.protocol_date, locale)}</span>
          </div>
        ) : null}
        <div className="dashboard-hero-text">
          {protocol ? <div className="dashboard-eyebrow">{t("nextSessionEyebrow")}</div> : null}
          <h2 className="dashboard-hero-title">{protocol ? protocol.title || protocol.protocol_number : t("noUpcomingSessionTitle")}</h2>
          {protocol ? (
            <div className="dashboard-hero-meta">
              <span>
                {formatDate(protocol.protocol_date)} · {protocol.protocol_number}
              </span>
              {countdown ? <span className="dashboard-countdown-pill">{countdown}</span> : null}
            </div>
          ) : (
            <p className="dashboard-hero-meta">{t("noUpcomingSessionDescription")}</p>
          )}
        </div>
        {protocol ? (
          <button type="button" className="button-secondary dashboard-hero-action" onClick={() => router.push(`/protocols/${protocol.id}`)}>
            {t("openProtocolButton")}
          </button>
        ) : null}
      </div>
      {firstSession ? (
        <div className="dashboard-hero-attendance">
          <ExcuseChips session={firstSession} canExcuse={canExcuse} busy={busy} onToggle={(s, e) => void toggleExcused(s, e)} variant="hero" />
        </div>
      ) : null}
    </section>
  );

  return (
    <div className="dashboard-page">
      {header}
      <div className="dashboard-columns">
        <div className="dashboard-column">
          {hero}

          {otherSessions.map((session) => (
            <section key={session.protocol!.id} className="card dashboard-card">
              <CardHeader title={t("excuseParticipantsEyebrow")} />
              <div className="dashboard-excuse-session">
                <strong>{session.protocol!.title || session.protocol!.protocol_number}</strong>
                <span className="muted">
                  {formatDate(session.protocol!.protocol_date)} · {session.protocol!.protocol_number}
                </span>
              </div>
              <ExcuseChips session={session} canExcuse={canExcuse} busy={busy} onToggle={(s, e) => void toggleExcused(s, e)} variant="card" />
            </section>
          ))}

          <section className="card dashboard-card">
            <CardHeader
              title={permissions.showSubmissions ? t("agendaWithDeadlinesTitle") : t("upcomingEventsEyebrow")}
              href={canWrite ? "/events" : undefined}
              linkLabel={t("allEventsLink")}
            />
            {agenda.length === 0 ? (
              <p className="muted">{t("noUpcomingEvents")}</p>
            ) : (
              <div className="dashboard-agenda">
                {agenda.map((group) => (
                  <div key={group.key} className="dashboard-agenda-group">
                    <div className="dashboard-agenda-label">
                      {group.label.type === "month" ? dateParts.monthYear(`${group.label.month}-01`, locale) : group.label.type === "thisWeek" ? t("thisWeek") : t("nextWeek")}
                    </div>
                    <div className="dashboard-list">
                      {group.items.map((item) => {
                        const content = (
                          <>
                            <span className="dashboard-agenda-day">
                              <span className="dashboard-agenda-day-number">{dateParts.day(item.date)}</span>
                              <span className="dashboard-agenda-day-weekday">{dateParts.weekdayShort(item.date, locale)}</span>
                            </span>
                            <span className={`dashboard-agenda-bar dashboard-agenda-bar-${item.kind}`} aria-hidden="true" />
                            <span className="dashboard-list-row-text">
                              <span className="dashboard-list-row-title">{item.title}</span>
                              {item.sub ? <span className="dashboard-list-row-sub">{item.sub}</span> : null}
                            </span>
                            <Badge variant={KIND_BADGE[item.kind]}>{t(`kind.${item.kind}`)}</Badge>
                            <span className="dashboard-list-row-meta dashboard-agenda-countdown">{countdownLabel(item.date, t)}</span>
                          </>
                        );
                        return item.href ? (
                          <button key={item.id} type="button" className="dashboard-list-row" onClick={() => router.push(item.href as Route)}>
                            {content}
                          </button>
                        ) : (
                          <div key={item.id} className="dashboard-list-row dashboard-list-row-static">
                            {content}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>

        <div className="dashboard-column">
          <section className="card dashboard-card">
            <CardHeader
              title={t("myTodosEyebrow")}
              badge={data.overdueCount > 0 ? <Badge variant="danger">{t("overdueCount", { count: data.overdueCount })}</Badge> : null}
              href="/todos"
              linkLabel={t("allButton")}
            />
            {data.myTodos.length === 0 ? (
              <p className="muted">{t("noOpenTodos")}</p>
            ) : (
              <div className="dashboard-list">
                {data.myTodos.slice(0, TODO_LIMIT).map((todo) => {
                  const overdue = isTodoOverdue(todo);
                  return (
                    <button key={todo.id} type="button" className="dashboard-list-row" onClick={() => router.push(todo.protocol_id ? `/protocols/${todo.protocol_id}` : "/todos")}>
                      <span className={`dashboard-todo-ring${overdue ? " dashboard-todo-ring-overdue" : ""}`} aria-hidden="true">{overdue ? "!" : ""}</span>
                      <span className="dashboard-list-row-text">
                        <span className="dashboard-list-row-title">{todo.task}</span>
                        <span className="dashboard-list-row-sub">{todo.protocol_number ?? t("withoutProtocol")}</span>
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

          {permissions.hasFinance ? (
            <section className="card dashboard-card">
              <CardHeader title={permissions.ownFinesOnly ? t("myOpenFinesEyebrow") : t("openFinesEyebrow")} href="/fines" linkLabel={t("allButton")} />
              {data.fineCount === 0 ? (
                <p className="muted">{permissions.ownFinesOnly ? t("noOwnOpenFines") : t("noOpenFines")}</p>
              ) : (
                <>
                  <div className="dashboard-card-total">
                    <span className="dashboard-card-total-value">{data.fineTotalLabel}</span>
                    {permissions.ownFinesOnly ? null : <span className="muted">{t("finePeople", { count: data.finePeople })}</span>}
                  </div>
                  <div className="dashboard-list">
                    {data.openFines.slice(0, FINE_LIMIT).map((fine) => (
                      <button key={fine.id} type="button" className="dashboard-list-row" onClick={() => router.push(`/protocols/${fine.protocol_id}`)}>
                        <span className="dashboard-initials" aria-hidden="true">{initials(fine.participant_name_snapshot)}</span>
                        <span className="dashboard-list-row-text">
                          <span className="dashboard-list-row-title">{fine.participant_name_snapshot}</span>
                          <span className="dashboard-list-row-sub">{fineTypeLabel[fine.fine_type] ?? fine.fine_type}</span>
                        </span>
                        <span className="dashboard-list-row-amount">{formatMoney(fine.amount, fine.currency_label ?? "", locale, { currencyFirst: true })}</span>
                      </button>
                    ))}
                  </div>
                </>
              )}
            </section>
          ) : null}

          {permissions.showAccounts ? (
            <section className="card dashboard-card">
              <CardHeader title={t("accountsEyebrow")} href="/finances" linkLabel={t("allButton")} />
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
                      <span className={`dashboard-list-row-amount${account.balance < 0 ? " dashboard-list-row-meta-overdue" : ""}`}>
                        {formatMoney(account.balance, account.currency_label, locale, { currencyFirst: true })}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </section>
          ) : null}
        </div>
      </div>
    </div>
  );
}
