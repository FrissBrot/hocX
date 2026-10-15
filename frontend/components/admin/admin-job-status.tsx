"use client";

import { useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { Badge, BadgeVariant } from "@/components/ui/badge";
import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { Modal } from "@/components/ui/modal";
import { Pagination } from "@/components/ui/pagination";
import { browserApiFetch } from "@/lib/api/client";
import { formatDateTime } from "@/lib/utils/format";
import { JobCategory, JobRunPage, JobState, JobStatusEntry, JobStatusOverview } from "@/types/api";

type Props = {
  initialOverview: JobStatusOverview;
};

type TFunc = ReturnType<typeof useTranslations>;

// Jobs laufen im Minuten- bis Tagestakt - 30 s reicht, damit ein Fehler ohne Neuladen auftaucht.
const POLL_INTERVAL_MS = 30_000;
const RUNS_PAGE_SIZE = 20;

// Reihenfolge der Abschnitte; "other" sammelt meldende, aber nicht registrierte Jobs.
const CATEGORY_ORDER: (JobCategory | "other")[] = ["virus_scan", "photo_analysis", "uploads", "documents", "storage", "backup", "cleanup", "maintenance", "other"];
const STATE_ORDER: JobState[] = ["failing", "overdue", "never_run", "running", "ok"];

const STATE_VARIANTS: Record<JobState, BadgeVariant> = {
  ok: "success",
  running: "info",
  failing: "danger",
  overdue: "warning",
  never_run: "neutral",
};

function formatInterval(seconds: number | null, t: TFunc): string {
  if (seconds === null) return t("interval.onDemand");
  if (seconds < 60) return t("interval.seconds", { count: seconds });
  if (seconds < 3600) return t("interval.minutes", { count: Math.round(seconds / 60) });
  if (seconds < 86400) return t("interval.hours", { count: Math.round(seconds / 3600) });
  return t("interval.days", { count: Math.round(seconds / 86400) });
}

function formatDuration(ms: number | null): string {
  if (ms === null) return "—";
  if (ms < 1000) return `${ms} ms`; // i18n-ok: Masseinheit
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${seconds} s`; // i18n-ok: Masseinheit
  return `${Math.floor(seconds / 60)} min ${seconds % 60} s`; // i18n-ok: Masseinheit
}

function jobTitle(job: JobStatusEntry, t: TFunc): string {
  // Registrierte Jobs haben feste Namen aus job_registry.py und darum einen Katalogeintrag unter
  // admin.jobs.jobNames - neue Jobs dort immer zusammen mit den Übersetzungen anlegen.
  return job.registered ? t(`jobNames.${job.name}.title`) : job.name;
}

function jobDescription(job: JobStatusEntry, t: TFunc): string | null {
  return job.registered ? t(`jobNames.${job.name}.description`) : null;
}

/** Zeitpunkt des letzten Lebenszeichens: Lauf oder (beim Worker) Heartbeat. */
function lastActivity(job: JobStatusEntry): string | null {
  const candidates = [job.last_finished_at, job.last_heartbeat_at].filter((value): value is string => value !== null);
  if (candidates.length === 0) return null;
  return candidates.reduce((latest, value) => (new Date(value) > new Date(latest) ? value : latest));
}

export function AdminJobStatus({ initialOverview }: Props) {
  const t = useTranslations("admin.jobs");
  const [overview, setOverview] = useState(initialOverview);
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const loadingRef = useRef(false);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      if (loadingRef.current) return;
      loadingRef.current = true;
      try {
        const result = await browserApiFetch<JobStatusOverview>("/api/admin/jobs");
        if (!cancelled) setOverview(result);
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

  const counts = STATE_ORDER.map((state) => ({ state, count: overview.items.filter((job) => job.state === state).length })).filter(
    (entry) => entry.count > 0,
  );
  const groups = CATEGORY_ORDER.map((category) => ({
    category,
    jobs: overview.items.filter((job) => (job.category ?? "other") === category),
  })).filter((group) => group.jobs.length > 0);
  const selectedJob = overview.items.find((job) => job.name === selectedName) ?? null;

  return (
    <div className="grid">
      <DataToolbar title={t("title")} description={t("description")} />

      <article className="card">
        <div className="admin-job-summary">
          {counts.map(({ state, count }) => (
            <Badge key={state} variant={STATE_VARIANTS[state]} dot>
              {t(`state.${state}`)}: {count}
            </Badge>
          ))}
          {overview.items.length === 0 && <span className="muted">{t("empty")}</span>}
        </div>
      </article>

      {groups.map(({ category, jobs }) => (
        <article key={category} className="card">
          <DataToolbar title={t(`category.${category}`)} />
          <DataTable
            columns={[t("columns.job"), t("columns.service"), t("columns.interval"), t("columns.lastActivity"), t("columns.duration"), t("columns.state")]}
          >
            {jobs.map((job) => (
              <JobRow key={job.name} job={job} onSelect={() => setSelectedName(job.name)} />
            ))}
          </DataTable>
        </article>
      ))}

      {selectedJob && <JobDetailModal job={selectedJob} onClose={() => setSelectedName(null)} />}
    </div>
  );
}

function JobRow({ job, onSelect }: { job: JobStatusEntry; onSelect: () => void }) {
  const t = useTranslations("admin.jobs");
  const locale = useLocale();
  const activity = lastActivity(job);
  const description = jobDescription(job, t);
  return (
    <tr
      className="table-row-clickable"
      onClick={onSelect}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect();
        }
      }}
      tabIndex={0}
    >
      <td>
        <div className="admin-job-name">{jobTitle(job, t)}</div>
        {description && <div className="muted admin-job-description">{description}</div>}
        {!job.registered && <Badge variant="neutral">{t("unregistered")}</Badge>}
      </td>
      <td className="muted">{job.service ? t(`service.${job.service}`) : "—"}</td>
      <td className="muted">{job.registered ? formatInterval(job.interval_seconds, t) : "—"}</td>
      <td className="muted">{activity ? formatDateTime(activity, locale) : "—"}</td>
      <td className="muted">{formatDuration(job.last_duration_ms)}</td>
      <td>
        <Badge variant={STATE_VARIANTS[job.state]}>{t(`state.${job.state}`)}</Badge>
        {job.consecutive_failures > 1 && (
          <div className="muted admin-job-description">{t("consecutiveFailures", { count: job.consecutive_failures })}</div>
        )}
      </td>
    </tr>
  );
}

function JobDetailModal({ job, onClose }: { job: JobStatusEntry; onClose: () => void }) {
  const t = useTranslations("admin.jobs");
  const locale = useLocale();
  const [runs, setRuns] = useState<JobRunPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [expandedRunId, setExpandedRunId] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    const params = new URLSearchParams({ limit: String(RUNS_PAGE_SIZE), offset: String(offset) });
    browserApiFetch<JobRunPage>(`/api/admin/jobs/${encodeURIComponent(job.name)}/runs?${params.toString()}`)
      .then((result) => {
        if (!cancelled) setRuns(result);
      })
      .catch(() => {
        if (!cancelled) setRuns({ items: [], total: 0 });
      });
    return () => {
      cancelled = true;
    };
  }, [job.name, offset]);

  const dateOrDash = (value: string | null) => (value ? formatDateTime(value, locale) : "—");
  const description = jobDescription(job, t);

  return (
    <Modal open title={jobTitle(job, t)} description={description ?? undefined} onClose={onClose} size="wide">
      <div className="grid">
        <dl className="admin-job-details">
          <dt>{t("details.state")}</dt>
          <dd>
            <Badge variant={STATE_VARIANTS[job.state]}>{t(`state.${job.state}`)}</Badge>
          </dd>
          <dt>{t("details.interval")}</dt>
          <dd>{job.registered ? formatInterval(job.interval_seconds, t) : "—"}</dd>
          <dt>{t("details.maxSilence")}</dt>
          <dd>{job.max_silence_seconds !== null ? formatInterval(job.max_silence_seconds, t) : "—"}</dd>
          <dt>{t("details.lastSuccess")}</dt>
          <dd>{dateOrDash(job.last_success_at)}</dd>
          <dt>{t("details.lastFailure")}</dt>
          <dd>{dateOrDash(job.last_failure_at)}</dd>
          {job.kind === "worker" && (
            <>
              <dt>{t("details.lastHeartbeat")}</dt>
              <dd>{dateOrDash(job.last_heartbeat_at)}</dd>
            </>
          )}
          <dt>{t("details.runs")}</dt>
          <dd>{t("details.runCounts", { runs: job.run_count, failures: job.failure_count })}</dd>
        </dl>

        {job.last_error && (
          <div className="grid admin-job-error-block">
            <span className="field-label">{t("details.lastError")}</span>
            <pre className="admin-job-error">{job.last_error}</pre>
          </div>
        )}

        <DataToolbar title={t("history.title")} description={t("history.description")} />
        <DataTable
          columns={[t("history.columns.finished"), t("history.columns.duration"), t("history.columns.result")]}
          emptyMessage={runs === null ? t("loading") : t("history.empty")}
        >
          {(runs?.items ?? []).map((run) => (
            <RunRows
              key={run.id}
              run={run}
              expanded={expandedRunId === run.id}
              onToggle={() => setExpandedRunId(expandedRunId === run.id ? null : run.id)}
            />
          ))}
        </DataTable>
        <Pagination offset={offset} limit={RUNS_PAGE_SIZE} total={runs?.total ?? 0} onOffsetChange={setOffset} />
      </div>
    </Modal>
  );
}

function RunRows({ run, expanded, onToggle }: { run: JobRunPage["items"][number]; expanded: boolean; onToggle: () => void }) {
  const t = useTranslations("admin.jobs");
  const locale = useLocale();
  const clickable = run.error !== null;
  return (
    <>
      <tr className={clickable ? "table-row-clickable" : undefined} onClick={clickable ? onToggle : undefined}>
        <td className="muted">{formatDateTime(run.finished_at, locale)}</td>
        <td className="muted">{formatDuration(run.duration_ms)}</td>
        <td>
          <Badge variant={run.status === "success" ? "success" : "danger"}>{t(`history.status.${run.status}`)}</Badge>
        </td>
      </tr>
      {expanded && run.error && (
        <tr>
          <td colSpan={3}>
            <pre className="admin-job-error">{run.error}</pre>
          </td>
        </tr>
      )}
    </>
  );
}
