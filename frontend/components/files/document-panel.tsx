"use client";

// Logische Dokumente im Datei-Detail (Design «Datei-Detail Popup v2»): Vorschau links (PDF-Ansicht
// bzw. extrahierter Text der gezeigten Version), Verarbeitungsstand und Versionsverlauf rechts.
import { useCallback, useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { ActionIcon } from "@/components/ui/action-icons";
import { Badge, BadgeVariant } from "@/components/ui/badge";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { useToast } from "@/contexts/toast-context";
import { browserApiBaseUrl, browserApiFetch } from "@/lib/api/client";
import { useVisibleInterval } from "@/lib/hooks/use-visible-interval";
import { avatarTone, participantInitials } from "@/lib/utils/avatar";
import { FileTypeIcon } from "./file-type-icon";
import { fileExtension } from "@/lib/files/display";
import { formatDateTime, formatFileSize } from "@/lib/utils/format";
import { DocumentDetail, DocumentJobState, DocumentStatus, DocumentSummary, DocumentText, DocumentVersionRead } from "@/types/api";

// Solange PDF oder Text noch erzeugt werden, holt der Dialog den Stand regelmässig neu.
const POLL_INTERVAL_MS = 5000;

export const DOCUMENT_STATUS_VARIANT: Record<DocumentStatus, BadgeVariant> = {
  processing: "info",
  ready: "success",
  partial: "warning",
  failed: "danger",
};

/** Lädt die Dokumentdetails zu einem Eintrag im Dateien-Tab und aktualisiert sie, solange die
 * Verarbeitung läuft. */
export function useDocumentDetail(summary: DocumentSummary | null | undefined) {
  const [detail, setDetail] = useState<DocumentDetail | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const detailUrl = summary?.detail_url ?? null;
  // Zählt Anfragen mit: eine verspätete Antwort für ein vorher angezeigtes Dokument (oder ein
  // überholter Polling-Lauf) darf den aktuellen Stand nicht überschreiben.
  const requestRef = useRef(0);

  const reload = useCallback(async () => {
    if (!detailUrl) return;
    const request = ++requestRef.current;
    try {
      const next = await browserApiFetch<DocumentDetail>(detailUrl);
      if (request !== requestRef.current) return;
      setDetail(next);
      setLoadFailed(false);
    } catch {
      if (request !== requestRef.current) return;
      setLoadFailed(true);
    }
  }, [detailUrl]);

  useEffect(() => {
    setDetail(null);
    void reload();
  }, [reload]);

  const processing = detail?.status === "processing";
  // Nur waehrend der Verarbeitung; pausiert in Hintergrund-Tabs.
  useVisibleInterval(() => void reload(), processing ? POLL_INTERVAL_MS : null);

  return { detail, loadFailed, reload };
}

export function currentVersion(detail: DocumentDetail | null): DocumentVersionRead | null {
  return detail?.versions.find((version) => version.is_current) ?? null;
}

/** Gezeigte Version: gewählt im Verlauf, sonst die aktuelle. */
export function shownVersion(detail: DocumentDetail | null, versionId: string | null): DocumentVersionRead | null {
  if (!detail) return null;
  return (versionId ? detail.versions.find((version) => version.id === versionId) : null) ?? currentVersion(detail);
}

/** Kleiner Avatar mit Initialen (Klassen .participant-avatar aus globals.css). */
export function PersonAvatar({ name }: { name: string }) {
  return (
    <span className={`participant-avatar participant-avatar-tone-${avatarTone(name)} file-detail-avatar`} aria-hidden="true">
      {participantInitials({ display_name: name })}
    </span>
  );
}

type StepState = "done" | "running" | "waiting" | "failed" | "none";


function scanState(scanStatus: string | undefined): StepState {
  if (scanStatus === "pending") return "running";
  if (scanStatus === "error" || scanStatus === "infected") return "failed";
  return "done";
}

function jobState(job: DocumentJobState, produced: boolean): StepState {
  if (produced) return "done";
  if (job.status === "running") return "running";
  if (job.status === "queued") return "waiting";
  // Fertig ohne Ergebnis (z. B. Format ohne PDF-Ansicht) bzw. nie eingereiht: nicht verfügbar.
  return job.status === "done" || job.status === "none" ? "none" : "failed";
}

function extractionState(version: DocumentVersionRead): StepState {
  const status = version.extraction?.status;
  if (status === "ready") return "done";
  if (status === "failed" || status === "ocr_required") return "failed";
  if (status) return "none";
  return jobState(version.extract_job, false);
}

/** Linke Spalte bei Dokumenten: Umschalter PDF-Ansicht / Extrahierter Text, Hinweis bei älterer
 * Version und die Vorschau der gezeigten Version. */
export function DocumentPreviewPane({
  detail,
  loadFailed,
  versionId,
  onShowCurrent,
  name,
  scanStatus,
  originalUrl,
}: {
  detail: DocumentDetail | null;
  loadFailed: boolean;
  versionId: string | null;
  onShowCurrent: () => void;
  name: string;
  scanStatus?: string;
  /** Originaldatei (Fallback ohne PDF-Ansicht). */
  originalUrl: string;
}) {
  const t = useTranslations("files");
  const showToast = useToast();
  const [mode, setMode] = useState<"pdf" | "text">("pdf");
  const [text, setText] = useState<string | null>(null);
  const [textLoading, setTextLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const version = shownVersion(detail, versionId);

  // Version im Verlauf gewählt: links wieder die PDF-Ansicht.
  useEffect(() => {
    setMode("pdf");
  }, [versionId]);
  const textUrl = version?.extraction?.text_url ?? null;

  // Text der gezeigten Version laden, sobald die Textansicht offen ist; verspätete Antworten
  // einer vorher gezeigten Version verwerfen.
  useEffect(() => {
    setText(null);
    if (mode !== "text" || !textUrl) return;
    let cancelled = false;
    setTextLoading(true);
    browserApiFetch<DocumentText>(`${textUrl}?format=plain`)
      .then((result) => { if (!cancelled) setText(result?.text ?? ""); })
      .catch(() => { if (!cancelled) showToast(t("document.textLoadError"), "error"); })
      .finally(() => { if (!cancelled) setTextLoading(false); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, textUrl]);

  useEffect(() => {
    if (!textUrl) setMode("pdf");
  }, [textUrl]);

  async function copyText() {
    try {
      await navigator.clipboard.writeText(text ?? "");
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      showToast(t("document.copyError"), "error");
    }
  }

  if (loadFailed) return <p className="file-detail-preview-note muted">{t("document.loadError")}</p>;
  if (!detail || !version) return <p className="file-detail-preview-note muted">{t("detail.loading")}</p>;

  const older = !version.is_current;

  return (
    <div className="file-detail-pane">
      <div className="file-detail-pane-bar">
        <FilterTabs
          options={[
            { value: "pdf", label: t("document.viewPdf") },
            { value: "text", label: t("document.viewText"), disabled: !textUrl, title: textUrl ? undefined : t("document.noText") },
          ]}
          value={mode}
          onChange={(value) => setMode(value as "pdf" | "text")}
        />
      </div>
      {older ? (
        <div className="file-detail-older" role="status">
          <span>{t("document.olderVersion", { number: version.version_number })}</span>
          <button type="button" className="button-secondary button-ghost" onClick={onShowCurrent}>{t("document.backToCurrent")}</button>
        </div>
      ) : null}
      <div className="file-detail-preview">
        {mode === "text" ? (
          textLoading || text === null ? (
            <p className="file-detail-preview-note muted">{t("detail.loading")}</p>
          ) : (
            <div className="file-detail-text-card">
              <div className="file-detail-text-head">
                <span>{t("document.textHead")}</span>
                <button type="button" className="button-secondary button-ghost file-detail-copy" onClick={() => void copyText()} disabled={!text}>
                  <ActionIcon name="copy" /> {copied ? t("document.textCopiedShort") : t("document.copyText")}
                </button>
              </div>
              <pre className="file-detail-text" aria-label={t("document.viewText")}>{text || t("document.textEmpty")}</pre>
            </div>
          )
        ) : version.pdf ? (
          <a href={`${browserApiBaseUrl}${version.pdf.url}`} target="_blank" rel="noreferrer" title={t("document.openPdfTitle")} className={version.preview ? "file-detail-preview-link" : "file-detail-preview-icon"}>
            {version.preview ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={`${browserApiBaseUrl}${version.preview.url}`} alt={t("document.previewTitle", { name })} className="file-detail-preview-img" />
            ) : (
              <span className="file-detail-preview-cta">{t("document.openPdf")}</span>
            )}
          </a>
        ) : detail.status === "processing" && version.is_current ? (
          <ProcessingSteps version={version} scanStatus={scanStatus} />
        ) : (
          <div className="file-detail-preview-empty">
            <span className="file-detail-preview-glyph"><FileTypeIcon name={version.original?.name ?? name} /></span>
            <p><strong>{t("document.noPdf")}</strong></p>
            <p className="muted">{t("document.noPdfHint")}</p>
            <a href={`${browserApiBaseUrl}${version.original?.url ?? originalUrl}`} target="_blank" rel="noreferrer" className="button-secondary">
              {t("detail.openOriginal")}
            </a>
          </div>
        )}
      </div>
    </div>
  );
}

function ProcessingSteps({ version, scanStatus }: { version: DocumentVersionRead; scanStatus?: string }) {
  const t = useTranslations("files");
  const steps: { key: "scan" | "pdf" | "text"; state: StepState }[] = [
    { key: "scan", state: scanState(scanStatus) },
    { key: "pdf", state: jobState(version.pdf_job, Boolean(version.pdf)) },
    { key: "text", state: extractionState(version) },
  ];
  return (
    <div className="file-detail-processing" role="status">
      <span className="file-detail-spinner" aria-hidden="true" />
      <p><strong>{t("document.previewProcessing")}</strong></p>
      <ol className="file-detail-steps">
        {steps.map((step) => (
          <li key={step.key} className={`file-detail-step file-detail-step-${step.state}`}>
            <span className={`file-detail-dot file-detail-dot-${step.state}`} aria-hidden="true" />
            {t(`document.step.${step.key}`)} <span className="muted">{t(`document.stepState.${step.state}`)}</span>
          </li>
        ))}
      </ol>
      <p className="muted">{t("document.autoRefresh")}</p>
    </div>
  );
}

/** Abschnitt «Dokument»: Virenprüfung, PDF-Ansicht und Text der gezeigten Version, bei
 * teilweise/fehlgeschlagener Verarbeitung Hinweis und «Erneut verarbeiten». */
export function DocumentStatusSection({
  detail,
  versionId,
  scanStatus,
  onReload,
}: {
  detail: DocumentDetail | null;
  versionId: string | null;
  scanStatus?: string;
  onReload: () => Promise<void>;
}) {
  const t = useTranslations("files");
  const showToast = useToast();
  const [reprocessing, setReprocessing] = useState(false);
  const version = shownVersion(detail, versionId);
  if (!detail || !version) return null;

  const scan = scanState(scanStatus);
  const pdf = jobState(version.pdf_job, Boolean(version.pdf));
  const extraction = extractionState(version);
  const cells = [
    { key: "scan", label: t("document.step.scan"), state: scan, value: t(`document.scanStatus.${scan}`) },
    { key: "pdf", label: t("document.step.pdf"), state: pdf, value: version.pdf ? t("document.pdfReady") : t(`document.jobStatus.${version.pdf_job.status}`) },
    {
      key: "text",
      label: t("document.step.text"),
      state: extraction,
      value: version.extraction ? t(`document.extractionStatus.${version.extraction.status}`) : t(`document.jobStatus.${version.extract_job.status}`),
    },
  ];
  const problem = version.is_current && (detail.status === "partial" || detail.status === "failed");

  async function reprocess() {
    if (!detail) return;
    setReprocessing(true);
    try {
      await browserApiFetch(`/api/documents/${detail.id}/reprocess`, { method: "POST" });
      showToast(t("document.reprocessStarted"), "success");
      await onReload();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("document.reprocessError"), "error");
    } finally {
      setReprocessing(false);
    }
  }

  return (
    <section className="file-detail-section">
      <h3 className="file-detail-section-title">{t("document.title")}</h3>
      <div className="file-detail-cells">
        {cells.map((cell) => (
          <div key={cell.key} className="file-detail-cell">
            <span className="file-detail-cell-label">{cell.label}</span>
            <span className="file-detail-cell-value">
              <span className={`file-detail-dot file-detail-dot-${cell.state}`} aria-hidden="true" />
              {cell.value}
            </span>
          </div>
        ))}
      </div>
      {problem ? (
        <div className={`file-detail-problem file-detail-problem-${detail.status}`}>
          <p>{t(detail.status === "failed" ? "document.problemFailed" : "document.problemPartial")}</p>
          {detail.can_reprocess ? (
            <button type="button" className="button-secondary" onClick={() => void reprocess()} disabled={reprocessing}>
              {reprocessing ? t("document.reprocessRunning") : t("document.reprocess")}
            </button>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

/** Reiter «Verlauf»: Versionen als Zeitleiste, ein Klick zeigt die Version links. */
export function DocumentVersionTimeline({
  detail,
  versionId,
  onSelect,
}: {
  detail: DocumentDetail | null;
  versionId: string | null;
  onSelect: (versionId: string | null) => void;
}) {
  const t = useTranslations("files");
  const locale = useLocale();
  if (!detail) return <p className="muted">{t("detail.loading")}</p>;
  const shown = shownVersion(detail, versionId);
  return (
    <div className="file-detail-history">
    <p className="muted file-detail-history-hint">{t("document.historyHint")}</p>
    <ol className="file-detail-timeline" aria-label={t("document.historyLabel")}>
      {detail.versions.map((entry) => {
        const isShown = shown?.id === entry.id;
        return (
          <li key={entry.id} className={`file-detail-timeline-item${isShown ? " file-detail-timeline-item-shown" : ""}`}>
            <span className="file-detail-timeline-dot" aria-hidden="true" />
            <div className="file-detail-timeline-body">
              <button
                type="button"
                className="file-detail-timeline-select"
                aria-pressed={isShown}
                onClick={() => onSelect(entry.is_current ? null : entry.id)}
              >
                <span className="file-detail-timeline-title">
                  {t("document.versionNumber", { number: entry.version_number })}
                  {entry.is_current ? <Badge variant="success">{t("document.current")}</Badge> : null}
                  {isShown && !entry.is_current ? <Badge variant="info">{t("document.shown")}</Badge> : null}
                  <span className="file-detail-timeline-date">{formatDateTime(entry.created_at, locale)}</span>
                </span>
                {entry.label ? <span className="file-detail-timeline-note">{entry.label}</span> : null}
                <span className="file-detail-timeline-meta">
                  {entry.created_by_name ? (
                    <span className="file-detail-person">
                      <PersonAvatar name={entry.created_by_name} />
                      {entry.created_by_name}
                    </span>
                  ) : null}
                  {entry.original ? (
                    <span className="file-detail-mono">
                      {[fileExtension(entry.original.name).toUpperCase() || null, formatFileSize(entry.original.size_bytes, locale) || null].filter(Boolean).join(" · ")}
                    </span>
                  ) : null}
                </span>
              </button>
              <span className="file-detail-timeline-links">
                {entry.pdf ? (
                  <a href={`${browserApiBaseUrl}${entry.pdf.url}`} target="_blank" rel="noreferrer">{t("document.openPdf")}</a>
                ) : null}
                {entry.original && entry.original.mime_type !== "application/pdf" ? (
                  <a href={`${browserApiBaseUrl}${entry.original.download_url}`} download>{t("document.original")}</a>
                ) : null}
              </span>
            </div>
          </li>
        );
      })}
    </ol>
    </div>
  );
}
