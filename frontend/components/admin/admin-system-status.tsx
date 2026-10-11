"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { Badge, BadgeVariant } from "@/components/ui/badge";
import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { StatusBanner } from "@/components/ui/status-banner";
import { browserApiFetch } from "@/lib/api/client";
import { formatDateTime, formatFileSize } from "@/lib/utils/format";
import { ContainerStatusEntry, HealthCheckEntry, HealthStatus, SystemHealthEvent, SystemProblem, SystemStatus } from "@/types/api";

type Props = {
  initialStatus: SystemStatus;
};

type TFunc = ReturnType<typeof useTranslations>;

// Der Snapshot wird alle 30 s neu gesammelt - 15 s Polling zeigt eine Änderung spätestens nach 45 s.
const POLL_INTERVAL_MS = 15_000;

const STATUS_VARIANTS: Record<HealthStatus, BadgeVariant> = {
  ok: "success",
  warning: "warning",
  critical: "danger",
  unknown: "neutral",
};

const SEVERITY_VARIANTS: Record<string, BadgeVariant> = {
  critical: "danger",
  warning: "warning",
  info: "success",
};

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

function eventText(event: SystemHealthEvent, t: TFunc): string {
  const { source, subject } = splitKey(event.subject);
  if (event.kind === "container_restart") return t("events.containerRestart", { subject });
  const text = problemText(source, subject, event.reason ?? "", t);
  return event.kind === "resolved" ? t("events.resolved", { text }) : text;
}

function formatUptime(startedAt: string | null, now: Date, t: TFunc): string {
  if (!startedAt) return "—";
  const minutes = Math.max(0, Math.floor((now.getTime() - new Date(startedAt).getTime()) / 60_000));
  if (minutes < 60) return t("uptime.minutes", { count: minutes });
  if (minutes < 60 * 24) return t("uptime.hours", { count: Math.floor(minutes / 60) });
  return t("uptime.days", { count: Math.floor(minutes / (60 * 24)) });
}

export function AdminSystemStatus({ initialStatus }: Props) {
  const t = useTranslations("admin.system");
  const locale = useLocale();
  const [status, setStatus] = useState(initialStatus);
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

  return (
    <div className="grid">
      <DataToolbar
        title={t("title")}
        description={t("description")}
        actions={
          <Link className="button-secondary" href="/admin/notifications">
            {t("notificationsLink")}
          </Link>
        }
      />

      <article className="card">
        <div className="grid">
          {status.stale ? (
            <StatusBanner
              tone="error"
              message={snapshot ? t("staleSince", { time: formatDateTime(snapshot.collected_at, locale) }) : t("noData")}
            />
          ) : status.problems.length === 0 ? (
            <StatusBanner tone="success" message={t("allGood")} />
          ) : (
            <StatusBanner tone="error" message={t("problemCount", { count: status.problems.length })} />
          )}
          {status.problems.length > 0 && <ProblemList problems={status.problems} />}
          {snapshot && <p className="muted admin-job-description">{t("collectedAt", { time: formatDateTime(snapshot.collected_at, locale) })}</p>}
        </div>
      </article>

      <article className="card">
        <DataToolbar title={t("checksTitle")} />
        {snapshot ? (
          <div className="admin-system-checks">
            {snapshot.checks.map((check) => (
              <CheckCard key={check.key} check={check} />
            ))}
          </div>
        ) : (
          <p className="muted">{t("noData")}</p>
        )}
      </article>

      <article className="card">
        <DataToolbar title={t("containersTitle")} description={snapshot?.compose_project ? t("composeProject", { project: snapshot.compose_project }) : undefined} />
        {snapshot && !snapshot.docker_configured && <StatusBanner tone="neutral" message={t("dockerNotConfigured")} />}
        {snapshot && snapshot.docker_configured && !snapshot.docker_available && (
          <StatusBanner tone="error" message={t("dockerUnavailable", { error: snapshot.docker_error ?? "" })} />
        )}
        {snapshot && snapshot.containers.length > 0 && (
          <DataTable
            columns={[t("containerColumns.service"), t("containerColumns.status"), t("containerColumns.uptime"), t("containerColumns.restarts"), t("containerColumns.cpu"), t("containerColumns.memory"), t("containerColumns.version")]}
          >
            {snapshot.containers.map((container) => (
              <ContainerRow key={container.container_id} container={container} now={now} />
            ))}
          </DataTable>
        )}
      </article>

      <article className="card">
        <DataToolbar title={t("eventsTitle")} description={t("eventsDescription")} />
        <DataTable columns={[t("eventColumns.time"), t("eventColumns.kind"), t("eventColumns.event")]} emptyMessage={t("noEvents")}>
          {status.events.map((event) => (
            <tr key={event.id}>
              <td className="muted">{formatDateTime(event.created_at, locale)}</td>
              <td>
                <Badge variant={SEVERITY_VARIANTS[event.severity] ?? "neutral"}>{t(`eventKinds.${event.kind}`)}</Badge>
              </td>
              <td>{eventText(event, t)}</td>
            </tr>
          ))}
        </DataTable>
      </article>
    </div>
  );
}

function ProblemList({ problems }: { problems: SystemProblem[] }) {
  const t = useTranslations("admin.system");
  const locale = useLocale();
  return (
    <ul className="admin-system-problems">
      {problems.map((problem) => (
        <li key={problem.key}>
          <Badge variant={problem.severity === "critical" ? "danger" : "warning"}>{t(`severity.${problem.severity}`)}</Badge>
          <span>
            {problem.source === "job" ? (
              <Link href="/admin/jobs">{problemText(problem.source, problem.subject, problem.reason, t)}</Link>
            ) : (
              problemText(problem.source, problem.subject, problem.reason, t)
            )}
          </span>
          {problem.first_seen_at && <span className="muted admin-job-description">{t("since", { time: formatDateTime(problem.first_seen_at, locale) })}</span>}
        </li>
      ))}
    </ul>
  );
}

function CheckCard({ check }: { check: HealthCheckEntry }) {
  const t = useTranslations("admin.system");
  const hasDetail = check.status !== "unknown" || Object.keys(check.params).length > 0;
  return (
    <div className="admin-system-check">
      <div className="admin-system-check-head">
        <span className="admin-job-name">{checkTitle(check.key, t)}</span>
        <Badge variant={STATUS_VARIANTS[check.status]}>{t(`status.${check.status}`)}</Badge>
      </div>
      <p className="muted admin-job-description">
        {check.error ? t("checkError", { error: check.error }) : hasDetail && t.has(`checks.${check.key}.detail`) ? t(`checks.${check.key}.detail`, check.params as Record<string, string | number>) : t("noDetails")}
      </p>
    </div>
  );
}

function ContainerRow({ container, now }: { container: ContainerStatusEntry; now: Date }) {
  const t = useTranslations("admin.system");
  const stateLabel = container.health ?? container.state;
  return (
    <tr>
      <td>
        <div className="admin-job-name">{container.service}</div>
        <div className="muted admin-job-description">{container.name}</div>
      </td>
      <td>
        <Badge variant={STATUS_VARIANTS[container.status]}>{stateLabel}</Badge>
        {container.reasons.map((reason) => (
          <div key={reason} className="muted admin-job-description">
            {t.has(`containerReasons.${reason}`) ? t(`containerReasons.${reason}`) : reason}
          </div>
        ))}
        {container.status !== "ok" && container.health_output && <pre className="admin-job-error">{container.health_output}</pre>}
      </td>
      <td className="muted">{container.state === "running" ? formatUptime(container.started_at, now, t) : "—"}</td>
      <td className="muted">{container.restart_count}</td>
      <td className="muted">{container.cpu_percent !== null ? `${container.cpu_percent.toLocaleString()} %` : "—"}</td>
      <td className="muted">
        {container.memory_bytes !== null
          ? container.memory_limit_bytes
            ? t("memoryOfLimit", { used: formatFileSize(container.memory_bytes), limit: formatFileSize(container.memory_limit_bytes) })
            : formatFileSize(container.memory_bytes)
          : "—"}
      </td>
      <td className="muted">{container.version ?? "—"}</td>
    </tr>
  );
}
