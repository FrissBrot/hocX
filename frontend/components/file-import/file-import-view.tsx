"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { Badge, type BadgeVariant } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { StatusBanner } from "@/components/ui/status-banner";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import {
  apiErrorCode,
  isActive,
  isCloudSource,
  readCloudReturn,
  type CloudProvider,
  type ImportJob,
  type ImportJobStatus,
  type PathedFile,
} from "@/lib/files/file-import";
import { formatDateTime } from "@/lib/utils/format";

import { ImportProgress } from "./import-progress";
import { ImportReport } from "./import-report";
import { ImportRulesStep } from "./import-rules-step";
import { ImportCloudStep } from "./import-cloud-step";
import { ImportSourceStep } from "./import-source-step";

const STATUS_VARIANT: Record<ImportJobStatus, BadgeVariant> = {
  draft: "neutral",
  listing: "info",
  ready: "info",
  queued: "info",
  running: "info",
  needs_reauth: "warning",
  cancel_requested: "warning",
  cancelled: "neutral",
  done: "success",
  failed: "danger",
};

export function ImportStatusBadge({ status }: { status: ImportJobStatus }) {
  const t = useTranslations("fileImport");
  return <Badge variant={STATUS_VARIANT[status]} dot>{t(`status.${status}`)}</Badge>;
}

const STEPS = ["source", "rules", "import", "report"] as const;

function stepOf(job: ImportJob | null): (typeof STEPS)[number] {
  if (!job || job.status === "draft" || job.status === "listing") return "source";
  if (job.status === "ready") return "rules";
  if (["queued", "running", "needs_reauth", "cancel_requested"].includes(job.status)) return "import";
  return "report";
}

export function FileImportView({ initialJobs, providers }: { initialJobs: ImportJob[]; providers: CloudProvider[] }) {
  const t = useTranslations("fileImport");
  const locale = useLocale();
  const showToast = useToast();
  // Rückkehr vom Anbieter (OAuth-Callback): Fehlercode in der Query, Abschluss-Token im Fragment
  const [cloudError, setCloudError] = useState<string | null>(null);
  const finishing = useRef(false);
  const [jobs, setJobs] = useState<ImportJob[]>(initialJobs);
  const [selectedId, setSelectedId] = useState<string | null>(() => initialJobs.find(isActive)?.id ?? null);
  const [startingNew, setStartingNew] = useState(false);
  // Ordner-Quelle: die gewählten Dateien bleiben nur im Speicher dieser Seite (nie im Browser-Speicher).
  const folderFiles = useRef<Map<string, File>>(new Map());

  const selected = jobs.find((job) => job.id === selectedId) ?? null;
  const active = jobs.find(isActive) ?? null;

  const reload = useCallback(async () => {
    const next = await browserApiFetch<ImportJob[]>("/api/cloud-import/jobs");
    setJobs(next);
    return next;
  }, []);

  const replaceJob = useCallback((job: ImportJob) => {
    setJobs((current) => (current.some((entry) => entry.id === job.id) ? current.map((entry) => (entry.id === job.id ? job : entry)) : [job, ...current]));
    setSelectedId(job.id);
  }, []);

  useEffect(() => {
    if (active && !selectedId && !startingNew) setSelectedId(active.id);
  }, [active, selectedId, startingNew]);

  useEffect(() => {
    const result = readCloudReturn(window.location.search, window.location.hash);
    if (!result.job && !result.error && !result.notice && !result.finish) return;
    // Token und Codes sofort aus Adresszeile und Verlauf entfernen
    window.history.replaceState(null, "", window.location.pathname);
    if (result.job) setSelectedId(result.job);
    if (result.notice) showToast(t.has(`cloud.notices.${result.notice}`) ? t(`cloud.notices.${result.notice}`) : t("cloud.notices.generic"), "info");
    if (result.error) setCloudError(result.error);
    if (!result.finish || finishing.current) return;
    finishing.current = true;
    browserApiFetch<ImportJob>("/api/cloud-import/oauth/finish", { method: "POST", body: JSON.stringify({ token: result.finish }) })
      .then((job) => {
        replaceJob(job);
        setCloudError(null);
        showToast(t("cloud.connectedToast", { account: job.connection?.account_label ?? "" }), "success");
      })
      .catch((error) => setCloudError(apiErrorCode(error) ?? "generic"));
  }, [replaceJob, showToast, t]);

  function rememberFiles(files: PathedFile[]) {
    folderFiles.current = new Map(files.map((entry) => [entry.path, entry.file]));
  }

  const step = startingNew ? "source" : stepOf(selected);
  const readOnly = selected !== null && !selected.is_owner;

  return (
    <div className="grid file-import-page">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("title")}</h1>
          <p className="muted">{t("intro")}</p>
        </div>
        <div className="table-toolbar-actions">
          <Link href="/files" className="button-ghost">{t("backToFiles")}</Link>
          {!active && !startingNew && selected ? (
            <button type="button" className="button-primary" onClick={() => { setSelectedId(null); setStartingNew(true); }}>
              {t("newImport")}
            </button>
          ) : null}
        </div>
      </div>

      <ol className="file-import-steps" aria-label={t("steps.label")}>
        {STEPS.map((entry, index) => (
          <li
            key={entry}
            className={entry === step ? "file-import-step file-import-step-current" : "file-import-step"}
            aria-current={entry === step ? "step" : undefined}
          >
            <span className="file-import-step-number">{index + 1}</span>
            {t(`steps.${entry}`)}
          </li>
        ))}
      </ol>

      {readOnly && selected ? (
        <StatusBanner tone="neutral" message={t("othersImport", { name: selected.requested_by_name ?? t("someone") })} />
      ) : null}

      {step === "source" && !readOnly && selected && !startingNew && isCloudSource(selected.source) ? (
        <ImportCloudStep
          job={selected}
          provider={providers.find((entry) => entry.key === selected.source) ?? null}
          returnError={cloudError}
          onJob={(job) => { setCloudError(null); replaceJob(job); }}
          onCancelled={async () => { setSelectedId(null); await reload(); }}
        />
      ) : null}
      {step === "source" && !readOnly && !(selected && !startingNew && isCloudSource(selected.source)) ? (
        <ImportSourceStep
          providers={providers}
          job={startingNew ? null : selected}
          blocked={active !== null && (startingNew || selected === null)}
          onJob={(job) => { setStartingNew(false); replaceJob(job); }}
          onFiles={rememberFiles}
          onCancelled={async () => { setStartingNew(false); setSelectedId(null); await reload(); }}
        />
      ) : null}
      {step === "rules" && selected ? (
        <ImportRulesStep job={selected} readOnly={readOnly} onJob={replaceJob} onCancelled={async () => { setSelectedId(null); await reload(); }} />
      ) : null}
      {step === "import" && selected ? (
        <ImportProgress
          job={selected}
          provider={providers.find((entry) => entry.key === selected.source) ?? null}
          onJob={replaceJob}
          folderFiles={folderFiles}
          onFiles={rememberFiles}
        />
      ) : null}
      {step === "report" && selected ? <ImportReport job={selected} onJob={replaceJob} /> : null}

      <section className="section-card file-import-history">
        <h2 className="section-title">{t("history.title")}</h2>
        <DataTable
          columns={[t("history.started"), t("history.source"), t("history.files"), t("history.status"), t("history.by"), ""]}
          emptyMessage={t("history.empty")}
        >
          {jobs.map((job) => (
            <tr key={job.id} className={job.id === selectedId ? "file-import-history-current" : undefined}>
              <td>{formatDateTime(job.started_at ?? job.created_at, locale)}</td>
              <td>{t(job.takeout ? "source.takeout" : isCloudSource(job.source) ? `source.provider.${job.source}` : `source.${job.source}`)}</td>
              <td>{t("history.fileCount", { count: job.total_items })}</td>
              <td><ImportStatusBadge status={job.status} /></td>
              <td>{job.requested_by_name ?? "–"}</td>
              <td>
                <button type="button" className="button-secondary button-ghost" onClick={() => { setStartingNew(false); setSelectedId(job.id); }}>
                  {t("history.open")}
                </button>
              </td>
            </tr>
          ))}
        </DataTable>
      </section>
    </div>
  );
}
