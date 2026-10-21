"use client";

import Link from "next/link";
import type { Route } from "next";
import { useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { DataTable } from "@/components/ui/data-table";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { StatusBanner } from "@/components/ui/status-banner";
import { browserApiFetch } from "@/lib/api/client";
import { formatDateTime, formatFileSize, formatTime, formatWeekdayDate } from "@/lib/utils/format";
import { ContainerStatusEntry, HealthCheckEntry, HealthStatus, SystemHealthEvent, SystemProblem, SystemStatus } from "@/types/api";

type Props = {
  initialStatus: SystemStatus;
};

type TFunc = ReturnType<typeof useTranslations>;

// Der Snapshot wird alle 30 s neu gesammelt - 15 s Polling zeigt eine Änderung spätestens nach 45 s.
const POLL_INTERVAL_MS = 15_000;

// Reihenfolge innerhalb einer Gruppe: Auffälliges zuerst.
const STATUS_ORDER: Record<HealthStatus, number> = { critical: 0, warning: 1, unknown: 2, ok: 3 };

// Fachliche Gruppen der Dienstprüfungen (Schlüssel aus system_health_service.collect_checks).
// Unbekannte Schlüssel landen in "other", damit eine neue Prüfung nie verschwindet.
const CHECK_GROUPS: { key: string; checks: string[] }[] = [
  { key: "infrastructure", checks: ["postgres", "redis", "storage", "object_storage", "storage_migration", "local_s3", "orphaned_files"] },
  { key: "security", checks: ["clamav", "clamav_signatures", "scan_backlog", "document_verification", "security"] },
  { key: "processing", checks: ["runtime", "photo_queue", "document_queue", "error_rate"] },
  { key: "backup", checks: ["backup", "backup_repository", "backup_verification"] },
];

// Wohin ein Problem führt (Link rechts in der Problemliste).
function problemLink(problem: SystemProblem): { href: Route | "#containers"; label: string } | null {
  if (problem.source === "job") return { href: "/admin/jobs", label: "jobs" };
  if (problem.source === "check" && ["storage", "object_storage", "storage_migration", "local_s3"].includes(problem.subject)) {
    return { href: "/admin/storage", label: "storage" };
  }
  if (problem.source === "check" && problem.subject.startsWith("backup")) return { href: "/admin/backups", label: "backups" };
  if (problem.source === "container") return { href: "#containers", label: "containers" };
  return null;
}

function checkTitle(key: string, t: TFunc): string {
  return t.has(`checks.${key}.title`) ? t(`checks.${key}.title`) : key;
}

/** Problem-Schlüssel "<quelle>:<subjekt>[:<zusatz>]" plus Grund -> übersetzter Text. */
function problemText(source: string, subject: string, reason: string, t: TFunc): string {
  if (source === "check") {
    if (reason === "unreachable") return t("problems.check.unreachable", { subject: checkTitle(subject, t) });
    return t.has(`checks.${subject}.problem`) ? t(`checks.${subject}.problem`) : checkTitle(subject, t);
  }
  const key = `problems.${source}.${reason}`;
  return t.has(key) ? t(key, { subject }) : `${source}:${subject} (${reason})`; // i18n-ok: Fallback für unbekannte Schlüssel
}

function splitKey(key: string): { source: string; subject: string } {
  const [source, subject = ""] = key.split(":");
  return { source, subject };
}

// Die Art (Problem/Behoben/Neustart) steht als eigene Markierung daneben, der Text bleibt neutral.
function eventText(event: SystemHealthEvent, t: TFunc): string {
  const { source, subject } = splitKey(event.subject);
  if (event.kind === "container_restart") return t("events.containerRestart", { subject });
  return problemText(source, subject, event.reason ?? "", t);
}

function formatUptime(startedAt: string | null, now: Date, t: TFunc): string {
  if (!startedAt) return "—";
  const minutes = Math.max(0, Math.floor((now.getTime() - new Date(startedAt).getTime()) / 60_000));
  if (minutes < 60) return t("uptime.minutes", { count: minutes });
  if (minutes < 60 * 24) return t("uptime.hours", { count: Math.floor(minutes / 60) });
  return t("uptime.days", { count: Math.floor(minutes / (60 * 24)) });
}

/** Belegung in Prozent für Prüfungen mit Füllstand (Speicherplatz, Backup-Repository). */
function checkUsage(check: HealthCheckEntry): number | null {
  const { freePercent, usedPercent, quota } = check.params;
  if (check.key === "storage" && typeof freePercent === "number") return Math.min(100, Math.max(0, 100 - freePercent));
  if (check.key === "backup_repository" && quota === "yes" && typeof usedPercent === "number") return Math.min(100, Math.max(0, usedPercent));
  return null;
}

function localDay(iso: string): string {
  const date = new Date(iso);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

export function AdminSystemStatus({ initialStatus }: Props) {
  const t = useTranslations("admin.system");
  const locale = useLocale();
  const [status, setStatus] = useState(initialStatus);
  const [filter, setFilter] = useState<"all" | "problems">("all");
  const loadingRef = useRef(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      if (loadingRef.current) return;
      loadingRef.current = true;
      try {
        const result = await browserApiFetch<SystemStatus>("/api/admin/system-status");
        if (!cancelled) setStatus(result);
      } catch {
        // Letzten Stand weiter zeigen statt die Ansicht bei einem kurzen Fehler zu leeren.
      } finally {
        loadingRef.current = false;
      }
    }
    const interval = setInterval(() => void load(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  const snapshot = status.snapshot;
  const now = snapshot ? new Date(snapshot.collected_at) : new Date();
  const checks = snapshot?.checks ?? [];
  const critical = status.problems.filter((problem) => problem.severity === "critical").length;
  const warnings = status.problems.length - critical;
  const okChecks = checks.filter((check) => check.status === "ok").length;
  const unknownChecks = checks.filter((check) => check.status === "unknown").length;
  const tone = status.stale || critical > 0 ? "critical" : warnings > 0 ? "warning" : "ok";
  const heroTitle = status.stale
    ? t("hero.stale")
    : critical > 0
      ? t("hero.critical", { critical, warnings })
      : warnings > 0
        ? t("hero.warnings", { count: warnings })
        : t("hero.allGood");

  const known = new Set(CHECK_GROUPS.flatMap((group) => group.checks));
  const groups = [...CHECK_GROUPS, { key: "other", checks: checks.map((check) => check.key).filter((key) => !known.has(key)) }]
    .map((group) => {
      const items = checks.filter((check) => group.checks.includes(check.key));
      return {
        key: group.key,
        total: items.length,
        ok: items.filter((check) => check.status === "ok").length,
        items: items
          .filter((check) => filter === "all" || check.status !== "ok")
          .sort((a, b) => STATUS_ORDER[a.status] - STATUS_ORDER[b.status]),
      };
    })
    .filter((group) => group.items.length > 0);

  const containers = snapshot?.containers ?? [];
  const restarts = containers.reduce((sum, container) => sum + container.restart_count, 0);

  const eventDays: { day: string; items: SystemHealthEvent[] }[] = [];
  for (const event of status.events) {
    const day = localDay(event.created_at);
    const last = eventDays[eventDays.length - 1];
    if (last && last.day === day) last.items.push(event);
    else eventDays.push({ day, items: [event] });
  }

  return (
    <div className="grid admin-status-page">
      <div className="page-header admin-status-header">
        <div>
          <h1 className="page-title">{t("title")}</h1>
          <p className="muted">{t("description")}</p>
        </div>
        <div className="admin-status-header-actions">
          {snapshot && (
            <span className={`admin-status-live${status.stale ? " admin-status-live-stale" : ""}`}>
              <span className="admin-status-live-dot" aria-hidden="true" />
              {t(status.stale ? "staleBadge" : "liveBadge", { time: formatDateTime(snapshot.collected_at, locale) })}
            </span>
          )}
          <Link className="button-secondary" href="/admin/notifications">
            {t("notificationsLink")}
          </Link>
        </div>
      </div>

      {status.stale && (
        <StatusBanner
          tone="error"
          message={snapshot ? t("staleSince", { time: formatDateTime(snapshot.collected_at, locale) }) : t("noData")}
        />
      )}

      <section className={`admin-status-hero admin-status-tone-${tone}`} aria-label={t("hero.label")}>
        <div className="admin-status-hero-summary">
          <span className="admin-status-eyebrow">{t("hero.label")}</span>
          <h2 className="admin-status-hero-title">{heroTitle}</h2>
          <div className="admin-status-tally">
            <TallyChip status="critical" count={critical} label={t("tally.critical", { count: critical })} />
            <TallyChip status="warning" count={warnings} label={t("tally.warning", { count: warnings })} />
            <TallyChip status="ok" count={okChecks} label={t("tally.ok", { count: okChecks })} />
            <TallyChip status="unknown" count={unknownChecks} label={t("tally.unknown", { count: unknownChecks })} />
          </div>
        </div>
        <div className="admin-status-hero-problems">
          {status.problems.length > 0 ? (
            <ProblemList problems={status.problems} />
          ) : (
            <p className="muted">{t("noProblems")}</p>
          )}
        </div>
      </section>

      <section className="admin-status-section">
        <div className="admin-status-section-head">
          <h2 className="admin-status-section-title">{t("checksTitle")}</h2>
          <FilterTabs
            options={[
              { value: "all", label: t("filters.all") },
              { value: "problems", label: t("filters.problems") },
            ]}
            value={filter}
            onChange={(value) => setFilter(value as "all" | "problems")}
          />
        </div>
        {!snapshot ? (
          <p className="muted">{t("noData")}</p>
        ) : groups.length === 0 ? (
          <p className="muted">{t("noIssues")}</p>
        ) : (
          <div className="admin-status-groups">
            {groups.map((group) => (
              <article key={group.key} className="admin-status-group">
                <div className="admin-status-group-head">
                  <h3 className="admin-status-eyebrow">{t(`groups.${group.key}`)}</h3>
                  <span className="admin-status-group-summary">{t("groupSummary", { ok: group.ok, total: group.total })}</span>
                </div>
                {group.items.map((check) => (
                  <CheckRow key={check.key} check={check} />
                ))}
              </article>
            ))}
          </div>
        )}
      </section>

      <section id="containers" className="card admin-status-card">
        <div className="admin-status-card-head">
          <h2 className="admin-status-section-title">{t("containersTitle")}</h2>
          {snapshot && snapshot.containers.length > 0 && (
            <span className="admin-status-card-meta">
              {snapshot.compose_project && (
                <>
                  {t.rich("composeProjectRich", { project: snapshot.compose_project, mono: (chunks) => <code>{chunks}</code> })}
                  {" · "}
                </>
              )}
              {t("containerSummary", { count: containers.length, restarts })}
            </span>
          )}
        </div>
        {snapshot && !snapshot.docker_configured && <StatusBanner tone="neutral" message={t("dockerNotConfigured")} />}
        {snapshot && snapshot.docker_configured && !snapshot.docker_available && (
          <StatusBanner tone="error" message={t("dockerUnavailable", { error: snapshot.docker_error ?? "" })} />
        )}
        {containers.length > 0 && (
          <DataTable
            className="admin-status-containers"
            columns={[t("containerColumns.service"), t("containerColumns.status"), t("containerColumns.uptime"), t("containerColumns.cpu"), t("containerColumns.memory"), t("containerColumns.version")]}
          >
            {containers.map((container) => (
              <ContainerRow key={container.container_id} container={container} now={now} />
            ))}
          </DataTable>
        )}
      </section>

      <section className="card admin-status-card">
        <div className="admin-status-card-head">
          <div>
            <h2 className="admin-status-section-title">{t("eventsTitle")}</h2>
            <p className="muted admin-status-card-meta">{t("eventsDescription")}</p>
          </div>
        </div>
        {eventDays.length === 0 ? (
          <p className="muted">{t("noEvents")}</p>
        ) : (
          eventDays.map((day) => (
            <div key={day.day} className="admin-status-event-day">
              <h3 className="admin-status-eyebrow">{formatWeekdayDate(day.day, locale)}</h3>
              <ul className="admin-status-events">
                {day.items.map((event) => (
                  <li key={event.id} className={`admin-status-event admin-status-event-${event.kind}`}>
                    <time dateTime={event.created_at}>{formatTime(event.created_at, locale)}</time>
                    <span className="admin-status-dot" aria-hidden="true" />
                    <span>{eventText(event, t)}</span>
                    <span className="admin-status-event-kind">{t(`eventKinds.${event.kind}`)}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))
        )}
      </section>
    </div>
  );
}

function TallyChip({ status, count, label }: { status: HealthStatus; count: number; label: string }) {
  return (
    <span className={`admin-status-chip admin-status-${status}`}>
      <span className="admin-status-dot" aria-hidden="true" />
      <strong>{count}</strong> {label}
    </span>
  );
}

function ProblemList({ problems }: { problems: SystemProblem[] }) {
  const t = useTranslations("admin.system");
  const locale = useLocale();
  return (
    <ul className="admin-system-problems">
      {problems.map((problem) => {
        const link = problemLink(problem);
        return (
          <li key={problem.key} className={`admin-status-${problem.severity}`}>
            <span className="admin-status-dot" aria-hidden="true" />
            <div className="admin-system-problem-text">
              <span className="admin-system-problem-title">{problemText(problem.source, problem.subject, problem.reason, t)}</span>
              <span className="muted admin-status-small">
                {problem.first_seen_at ? `${t("since", { time: formatDateTime(problem.first_seen_at, locale) })} · ` : null}
                {t(`severity.${problem.severity}`)}
              </span>
            </div>
            {link?.href === "#containers" ? (
              <a className="admin-system-problem-link" href={link.href}>{t(`problemLinks.${link.label}`)}</a>
            ) : link ? (
              <Link className="admin-system-problem-link" href={link.href as Route}>
                {t(`problemLinks.${link.label}`)}
              </Link>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

function CheckRow({ check }: { check: HealthCheckEntry }) {
  const t = useTranslations("admin.system");
  const hasDetail = check.status !== "unknown" || Object.keys(check.params).length > 0;
  const usage = check.error ? null : checkUsage(check);
  return (
    <div className={`admin-system-check admin-status-${check.status}`}>
      <span className="admin-status-dot admin-status-dot-halo" aria-hidden="true" />
      <div className="admin-system-check-body">
        <div className="admin-system-check-head">
          <span className="admin-system-check-title">{checkTitle(check.key, t)}</span>
          <span className="admin-status-label">{t(`status.${check.status}`)}</span>
        </div>
        <p className="muted admin-status-small">
          {check.error ? t("checkError", { error: check.error }) : hasDetail && t.has(`checks.${check.key}.detail`) ? t(`checks.${check.key}.detail`, check.params as Record<string, string | number>) : t("noDetails")}
        </p>
        {usage !== null && (
          <span className="admin-status-bar" aria-hidden="true">
            <span style={{ width: `${usage}%` }} />
          </span>
        )}
      </div>
    </div>
  );
}

function ContainerRow({ container, now }: { container: ContainerStatusEntry; now: Date }) {
  const t = useTranslations("admin.system");
  // Sauber beendete Einmal-Container (z. B. storage-init) sind kein Problem, nur "beendet".
  const exitedOk = container.state === "exited" && container.status === "ok";
  const stateLabel = exitedOk ? t("containerStates.exitedOk") : container.health ?? container.state;
  // Laufende Container ohne Healthcheck in Blau, damit "healthy" (geprüft) davon unterscheidbar bleibt.
  const tone = container.status === "ok" && container.state === "running" && !container.health ? "running" : exitedOk ? "unknown" : container.status;
  const memoryPercent =
    container.memory_bytes !== null && container.memory_limit_bytes ? Math.min(100, (container.memory_bytes / container.memory_limit_bytes) * 100) : null;
  return (
    <tr>
      <td>
        <div className="admin-system-check-title">{container.service}</div>
        <div className="admin-status-mono">{container.name}</div>
      </td>
      <td>
        <span className={`admin-status-state admin-status-${tone}`}>
          <span className="admin-status-dot" aria-hidden="true" />
          {stateLabel}
        </span>
        {container.reasons.map((reason) => (
          <div key={reason} className="muted admin-status-small">
            {t.has(`containerReasons.${reason}`) ? t(`containerReasons.${reason}`) : reason}
          </div>
        ))}
        {container.restart_count > 0 && <div className="muted admin-status-small">{t("restartCount", { count: container.restart_count })}</div>}
        {container.status !== "ok" && container.health_output && <pre className="admin-job-error">{container.health_output}</pre>}
      </td>
      <td className="muted">{container.state === "running" ? formatUptime(container.started_at, now, t) : "—"}</td>
      <td className="muted admin-status-numeric">{container.cpu_percent !== null ? `${container.cpu_percent.toLocaleString()} %` : "—"}</td>
      <td>
        {container.memory_bytes !== null ? (
          <div className="admin-status-memory">
            <span className="admin-status-numeric">
              {container.memory_limit_bytes
                ? t("memoryOfLimit", { used: formatFileSize(container.memory_bytes), limit: formatFileSize(container.memory_limit_bytes) })
                : formatFileSize(container.memory_bytes)}
            </span>
            {memoryPercent !== null && (
              <span className={`admin-status-bar${memoryPercent > 80 ? " admin-status-bar-high" : ""}`} aria-hidden="true">
                <span style={{ width: `${memoryPercent}%` }} />
              </span>
            )}
          </div>
        ) : (
          <span className="muted">—</span>
        )}
      </td>
      <td className="admin-status-mono">{container.version ?? "—"}</td>
    </tr>
  );
}
