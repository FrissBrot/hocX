"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { Badge, BadgeVariant } from "@/components/ui/badge";
import { useToast } from "@/contexts/toast-context";
import { browserApiBaseUrl, browserApiFetch } from "@/lib/api/client";
import { formatDateTime } from "@/lib/utils/format";
import { DocumentDetail, DocumentStatus, DocumentSummary, DocumentText, DocumentVersionRead } from "@/types/api";

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
  useEffect(() => {
    if (!processing) return;
    const timer = setInterval(() => void reload(), POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [processing, reload]);

  return { detail, loadFailed, reload };
}

function currentVersion(detail: DocumentDetail | null): DocumentVersionRead | null {
  return detail?.versions.find((version) => version.is_current) ?? null;
}

/** Bevorzugte Ansicht: das PDF der aktuellen Version - als Bild der ersten Seite, ein Klick öffnet
 * das PDF im eigenen Tab (eingebettete Frames verbietet die CSP der App bewusst). */
export function DocumentPreview({ detail, name }: { detail: DocumentDetail | null; name: string }) {
  const t = useTranslations("files");
  const version = currentVersion(detail);
  if (version?.pdf) {
    return (
      <a
        href={`${browserApiBaseUrl}${version.pdf.url}`}
        target="_blank"
        rel="noreferrer"
        className={version.preview ? "file-detail-preview-link" : "file-detail-preview-icon"}
      >
        {version.preview ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={`${browserApiBaseUrl}${version.preview.url}`} alt={t("document.previewTitle", { name })} className="file-detail-preview-img" />
        ) : (
          <span className="file-detail-preview-cta">{t("document.openPdf")}</span>
        )}
      </a>
    );
  }
  const message = !detail
    ? t("detail.loading")
    : detail.status === "processing"
      ? t("document.previewProcessing")
      : t("document.previewUnavailable");
  return <p className="file-detail-preview-note muted">{message}</p>;
}

export function DocumentDetails({
  detail,
  loadFailed,
  onReload,
}: {
  detail: DocumentDetail | null;
  loadFailed: boolean;
  onReload: () => Promise<void>;
}) {
  const t = useTranslations("files");
  const locale = useLocale();
  const showToast = useToast();
  const [text, setText] = useState<string | null>(null);
  const [textOpen, setTextOpen] = useState(false);
  const [textLoading, setTextLoading] = useState(false);
  const [reprocessing, setReprocessing] = useState(false);
  const loadedTextUrl = useRef<string | null>(null);

  const version = currentVersion(detail);
  const extraction = version?.extraction ?? null;
  const textUrl = extraction?.text_url ?? null;

  useEffect(() => {
    // Neue Version oder anderes Dokument: angezeigten Text verwerfen.
    if (textUrl !== loadedTextUrl.current) {
      setText(null);
      setTextOpen(false);
    }
  }, [textUrl]);

  if (loadFailed) {
    return <p className="muted">{t("document.loadError")}</p>;
  }
  if (!detail || !version) {
    return <p className="muted">{t("detail.loading")}</p>;
  }

  async function toggleText() {
    if (textOpen) {
      setTextOpen(false);
      return;
    }
    if (text === null && textUrl) {
      setTextLoading(true);
      try {
        const result = await browserApiFetch<DocumentText>(`${textUrl}?format=plain`);
        setText(result?.text ?? "");
        loadedTextUrl.current = textUrl;
      } catch {
        showToast(t("document.textLoadError"), "error");
        return;
      } finally {
        setTextLoading(false);
      }
    }
    setTextOpen(true);
  }

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
    <>
      <section className="file-detail-section">
        <h3 className="file-detail-section-title">{t("document.title")}</h3>
        <dl className="file-detail-meta-list">
          <div>
            <dt>{t("document.status")}</dt>
            <dd><Badge variant={DOCUMENT_STATUS_VARIANT[detail.status]}>{t(`document.statusLabel.${detail.status}`)}</Badge></dd>
          </div>
          <div>
            <dt>{t("document.pdf")}</dt>
            <dd>{version.pdf ? t("document.pdfReady") : t(`document.jobStatus.${version.pdf_job.status}`)}</dd>
          </div>
          <div>
            <dt>{t("document.text")}</dt>
            <dd>
              {extraction
                ? t(`document.extractionStatus.${extraction.status}`)
                : t(`document.jobStatus.${version.extract_job.status}`)}
            </dd>
          </div>
          {detail.versions.length > 1 || version.label ? (
            <div>
              <dt>{t("document.currentVersion")}</dt>
              <dd>{version.label ?? t("document.versionNumber", { number: version.version_number })}</dd>
            </div>
          ) : null}
        </dl>
        <div className="file-detail-actions">
          {version.pdf ? (
            <a href={`${browserApiBaseUrl}${version.pdf.download_url}`} className="button-secondary" download>
              {t("document.downloadPdf")}
            </a>
          ) : null}
          {version.original && version.original.mime_type !== "application/pdf" ? (
            <a href={`${browserApiBaseUrl}${version.original.download_url}`} className="button-secondary button-ghost" download>
              {t("document.downloadOriginal")}
            </a>
          ) : null}
          {textUrl ? (
            <button type="button" className="button-secondary button-ghost" onClick={() => void toggleText()} disabled={textLoading}>
              {textOpen ? t("document.hideText") : t("document.showText")}
            </button>
          ) : null}
          {detail.can_reprocess ? (
            <button type="button" className="button-secondary button-ghost" onClick={() => void reprocess()} disabled={reprocessing}>
              {t("document.reprocess")}
            </button>
          ) : null}
        </div>
        {textOpen ? (
          <pre className="file-detail-text" aria-label={t("document.text")}>
            {text || t("document.textEmpty")}
          </pre>
        ) : null}
      </section>

      {detail.versions.length > 1 ? (
        <section className="file-detail-section">
          <h3 className="file-detail-section-title">{t("document.historyTitle", { count: detail.versions.length })}</h3>
          <ul className="file-detail-versions">
            {detail.versions.map((entry) => (
              <li key={entry.id} className="file-detail-version">
                <span className="file-detail-version-label">
                  {entry.label ?? t("document.versionNumber", { number: entry.version_number })}
                  {entry.is_current ? <Badge variant="success">{t("document.current")}</Badge> : null}
                </span>
                <span className="muted">{formatDateTime(entry.created_at, locale)}</span>
                <span className="file-detail-version-links">
                  {entry.pdf ? (
                    <a href={`${browserApiBaseUrl}${entry.pdf.url}`} target="_blank" rel="noreferrer">
                      {t("document.openPdf")}
                    </a>
                  ) : null}
                  {entry.original && entry.original.mime_type !== "application/pdf" ? (
                    <a href={`${browserApiBaseUrl}${entry.original.download_url}`} download>
                      {t("document.original")}
                    </a>
                  ) : null}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </>
  );
}
