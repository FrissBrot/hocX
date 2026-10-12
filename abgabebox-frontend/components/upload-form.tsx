"use client";

import { ChangeEvent, DragEvent, FormEvent, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { CaptchaWidget } from "@/components/captcha-widget";
import { useFlowDone } from "@/components/flow-steps";
import { publicApiUrl } from "@/lib/api";
import { validateUploadFiles, SUPPORTED_UPLOAD_EXTENSIONS } from "@/lib/validate-upload";

type Props = {
  linkToken: string;
  assignmentSlug: string;
  elementRef: string;
  assignmentTitle: string;
  elementLabel: string;
  allowedFileTypes: string[];
  maxFiles: number | null;
  maxFileSizeMb: number;
  alreadyUploadedCount: number;
  sitekey: string;
};

export function UploadForm({ linkToken, assignmentSlug, elementRef, assignmentTitle, elementLabel, allowedFileTypes, maxFiles, maxFileSizeMb, alreadyUploadedCount, sitekey }: Props) {
  const t = useTranslations("abgabebox.upload");
  const locale = useLocale();
  const setFlowDone = useFlowDone();
  const [files, setFiles] = useState<File[]>([]);
  const [dragging, setDragging] = useState(false);
  const [captchaSessionToken, setCaptchaSessionToken] = useState<string | null>(null);
  const [captchaVerifying, setCaptchaVerifying] = useState(false);
  const [captchaKey, setCaptchaKey] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [done, setDone] = useState(false);
  // Quittung der letzten Abgabe (Anzahl Dateien + Eingangszeit) fuer die Erfolgsansicht.
  const [receipt, setReceipt] = useState<{ files: number; at: Date } | null>(null);
  const [online, setOnline] = useState(true);
  const [uploadedSoFar, setUploadedSoFar] = useState(alreadyUploadedCount);
  const inputRef = useRef<HTMLInputElement>(null);
  // Welche rohe FriendlyCaptcha-Loesung bereits gegen ein Sitzungs-Token eingetauscht wurde -
  // handleSolved kann mehrfach mit derselben Loesung feuern (Callback + DOM-Fallback im Widget).
  const exchangedSolutionRef = useRef<string | null>(null);

  // Schrittanzeige im Seitenrahmen auf "Fertig" stellen, solange die Erfolgsansicht steht.
  useEffect(() => {
    setFlowDone(done);
  }, [done, setFlowDone]);
  useEffect(() => () => setFlowDone(false), [setFlowDone]);

  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    update();
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);

  const accept = (allowedFileTypes.length > 0 ? allowedFileTypes : SUPPORTED_UPLOAD_EXTENSIONS).map((ext) => `.${ext}`).join(",");
  const typeLabel = allowedFileTypes.length > 0 ? allowedFileTypes.map((ext) => ext.toUpperCase()).join(", ") : t("typeLabelDefault");
  const remaining = maxFiles === null ? null : Math.max(0, maxFiles - uploadedSoFar);

  function validateAndSet(selected: File[]): boolean {
    const result = validateUploadFiles(selected, { maxFiles, allowedFileTypes, maxFileSizeMb, alreadyUploaded: uploadedSoFar });
    if (!result.ok) {
      setError(t(`errors.${result.code}`, "params" in result ? result.params : undefined));
      return false;
    }
    setError(null);
    setFiles(selected);
    return true;
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    validateAndSet(Array.from(event.target.files ?? []));
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    validateAndSet(Array.from(event.dataTransfer.files));
  }

  function removeFile(index: number) {
    setFiles((prev) => prev.filter((_, i) => i !== index));
    setError(null);
  }

  function formatSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  // Laeuft einmal pro Seitenaufruf, sobald FriendlyCaptcha eine Loesung liefert - tauscht sie
  // sofort gegen ein serverseitig signiertes Sitzungs-Token (siehe abgabebox-backend
  // captcha-verify-Endpoint), das fuer alle weiteren Uploads auf dieser Seite gueltig bleibt.
  // Eine einzelne FriendlyCaptcha-Loesung selbst laesst sich nur einmal gegen deren Siteverify
  // pruefen, deshalb der Umweg ueber ein eigenes Token statt die Loesung direkt wiederzuverwenden.
  const handleSolved = useCallback(async (solution: string) => {
    if (exchangedSolutionRef.current === solution) return;
    exchangedSolutionRef.current = solution;
    setCaptchaVerifying(true);
    try {
      const formData = new FormData();
      formData.append("captcha_solution", solution);
      const response = await fetch(
        publicApiUrl(
          `/api/public/${encodeURIComponent(linkToken)}/assignments/${encodeURIComponent(assignmentSlug)}/elements/${encodeURIComponent(elementRef)}/captcha-verify`
        ),
        { method: "POST", body: formData, signal: AbortSignal.timeout(30_000) }
      );
      if (!response.ok) {
        // Eintausch fehlgeschlagen (z.B. FriendlyCaptcha-Loesung inzwischen abgelaufen) - Widget
        // neu montieren, statt in diesem bereits vom Widget als "geloest" markierten Zustand
        // stehenzubleiben, in dem keine neue Loesung mehr von selbst nachkaeme.
        setCaptchaVerifying(false);
        requestFreshCaptcha();
        return;
      }
      const result = await response.json();
      setCaptchaSessionToken(result.session_token);
      setCaptchaVerifying(false);
    } catch {
      setCaptchaVerifying(false);
      requestFreshCaptcha();
    }
  }, [linkToken, assignmentSlug, elementRef]);

  // Kein Sitekey konfiguriert (lokale Entwicklung/Test-Stack ohne eigene FriendlyCaptcha-Keys) -
  // das Widget kann gar nicht laden, also direkt den Backend-Austausch anstossen; captcha.py
  // laesst den Platzhalter-Wert durch, solange dort ebenfalls keine Keys gesetzt sind (siehe
  // captcha_enabled() im Backend). Ist doch ein Sitekey gesetzt, greift stattdessen der echte
  // Widget-Callback oben.
  useEffect(() => {
    if (!sitekey) {
      handleSolved("no-friendly-captcha-configured");
    }
  }, [sitekey, handleSolved]);

  // Startet einen frischen Sicherheitscheck (z.B. nach abgelaufenem Sitzungs-Token) - der `key`-
  // Wechsel zwingt React, das Widget komplett neu zu montieren, was dank data-start="auto" sofort
  // eine neue Challenge loest, ohne dass ausgewaehlte Dateien verloren gehen.
  function requestFreshCaptcha() {
    setCaptchaSessionToken(null);
    exchangedSolutionRef.current = null;
    setCaptchaKey((k) => k + 1);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (files.length === 0) { setError(t("errors.noFileSelected")); return; }
    if (!navigator.onLine) { setError(t("errors.offline")); return; }

    if (!captchaSessionToken) {
      setError(t("errors.captchaPending"));
      return;
    }

    setSubmitting(true);
    setError(null);
    setWarnings([]);
    try {
      const formData = new FormData();
      formData.append("captcha_session_token", captchaSessionToken);
      files.forEach((file) => formData.append("files", file));
      const response = await fetch(
        publicApiUrl(
          `/api/public/${encodeURIComponent(linkToken)}/assignments/${encodeURIComponent(assignmentSlug)}/elements/${encodeURIComponent(elementRef)}/upload`
        ),
        { method: "POST", body: formData, signal: AbortSignal.timeout(3 * 60 * 60 * 1000) }
      );
      if (!response.ok) {
        if (response.status === 429) {
          throw new Error(t("errors.tooManyRequests"));
        }
        if (response.status === 401) {
          // Sitzungs-Token abgelaufen (siehe ABGABEBOX_CAPTCHA_SESSION_TTL_MINUTES) - Widget fuer
          // eine frische Loesung neu starten, ausgewaehlte Dateien bleiben erhalten.
          requestFreshCaptcha();
          throw new Error(t("errors.captchaExpired"));
        }
        const body = await response.json().catch(() => null);
        // body?.detail kommt direkt vom Backend (abgabebox-backend liefert aktuell kuratierten
        // Freitext, keine stabilen Fehlercodes) - kann hier noch nicht lokalisiert werden, siehe
        // CLAUDE.md Abschnitt i18n Punkt 10 (kein unnoetiger Umbau des Error-Handlings).
        throw new Error(body?.detail ?? t("errors.uploadFailedGeneric"));
      }
      const result = await response.json().catch(() => null);
      setWarnings(result?.image_duplicate_warnings ?? []);
      setUploadedSoFar((prev) => prev + files.length);
      setReceipt({ files: files.length, at: new Date() });
      setFiles([]);
      setDone(true);
    } catch (err) {
      setError(navigator.onLine
        ? (err instanceof Error ? err.message : t("errors.uploadFailedGeneric"))
        : t("errors.connectionLost"));
    } finally {
      // Das Sitzungs-Token bleibt bewusst erhalten (ausser beim 401-Fall oben) - der
      // Sicherheitscheck soll nur einmal pro Seitenaufruf laufen, nicht vor jedem Upload.
      setSubmitting(false);
    }
  }

  const remainingAfterSuccess = maxFiles === null ? null : Math.max(0, maxFiles - uploadedSoFar);
  const canUploadMore = remainingAfterSuccess === null || remainingAfterSuccess > 0;

  if (done) {
    const receivedAt = receipt
      ? new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short", timeZone: "Europe/Zurich" }).format(receipt.at)
      : "";
    const rows: [string, string][] = [
      [t("receipt.assignment"), assignmentTitle],
      [t("receipt.element"), elementLabel],
      [t("receipt.files"), String(receipt?.files ?? 0)],
      [t("receipt.receivedAt"), receivedAt],
    ];
    return (
      <div className="upload-success" role="status">
        <span className="upload-success-icon" aria-hidden="true">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4"><path d="M5 13l4 4L19 7" /></svg>
        </span>
        <div className="upload-success-text">
          <h1>{t("successTitle")}</h1>
          <p className="muted muted-flush">{t("successCount", { count: uploadedSoFar })}</p>
        </div>
        <dl className="upload-receipt">
          {rows.map(([label, value]) => (
            <div key={label} className="upload-receipt-row">
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
        {warnings.length > 0 && (
          <div className="upload-warning-list">
            {warnings.map((warning, i) => (
              <p key={i}>{warning}</p>
            ))}
          </div>
        )}
        <div className="upload-success-actions">
          {canUploadMore ? (
            <button type="button" className="button" onClick={() => setDone(false)}>
              {t("uploadMore")}
            </button>
          ) : (
            <Link href={`/${linkToken}/${assignmentSlug}`} className="button">
              {t("otherElement")}
            </Link>
          )}
          <Link href={`/${linkToken}`} className="button button-outline">
            {t("toOverview")}
          </Link>
        </div>
      </div>
    );
  }

  const captchaReady = Boolean(captchaSessionToken);
  const submitDisabled = submitting || files.length === 0;

  return (
    <form onSubmit={handleSubmit} className="upload-form">
      {!online && <div className="upload-error" role="status">{t("offlineNotice")}</div>}
      {uploadedSoFar > 0 && (
        <p className="upload-already-count">
          {t("alreadyUploaded", { count: uploadedSoFar })}
        </p>
      )}

      <div
        className={`drop-zone${dragging ? " drop-zone-active" : ""}${files.length > 0 ? " drop-zone-filled" : ""}`}
        role="button"
        tabIndex={0}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); inputRef.current?.click(); } }}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
      >
        <input
          ref={inputRef}
          id="files"
          type="file"
          multiple={remaining === null || remaining > 1}
          accept={accept}
          onChange={handleFileChange}
          style={{ display: "none" }}
        />
        <span className="drop-zone-icon" aria-hidden="true">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9">
            <path d="M12 16V4M7 9l5-5 5 5" />
            <path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" />
          </svg>
        </span>
        <div className="drop-zone-label">
          {dragging ? (
            t("dropLabelRelease")
          ) : files.length > 0 ? (
            t("dropLabelSelected", { count: files.length })
          ) : (
            <>
              {/* Auf Touch-Geraeten gibt es kein Drag & Drop - dort nur "Datei auswaehlen" zeigen. */}
              <span className="drop-label-pointer">{t("dropLabelEmpty")}</span>
              <span className="drop-label-touch">{t("dropLabelEmptyTouch")}</span>
            </>
          )}
        </div>
        <div className="drop-zone-hint">
          {typeLabel} · {remaining === null ? t("hintMaxFilesUnbounded") : t("hintMaxFilesRemaining", { count: remaining })} · {t("hintPerFile", { size: maxFileSizeMb })} · {t("hintTotal")}
        </div>
      </div>

      {files.length > 0 && (
        <ul className="file-list">
          {files.map((file, i) => {
            const ext = fileExtension(file.name);
            return (
              <li key={i} className="file-item">
                <span className={`file-ext file-ext-${extensionTone(ext)}`} aria-hidden="true">{ext || "·"}</span>
                <span className="file-text">
                  <span className="file-name">{file.name}</span>
                  <span className="file-size">{formatSize(file.size)}</span>
                </span>
                <button type="button" className="file-remove" onClick={() => removeFile(i)} aria-label={t("removeFile")}>✕</button>
              </li>
            );
          })}
        </ul>
      )}

      {error && <p className="error">{error}</p>}

      <div className="upload-actions">
        {/* Captcha - laeuft einmal beim Laden der Seite, bleibt danach fuer alle weiteren Uploads
            gueltig (siehe handleSolved oben) - das Widget selbst wird nach erfolgreichem Eintausch
            ausgeblendet, nur der Status bleibt sichtbar. Ohne Sitekey (kein FriendlyCaptcha
            konfiguriert) zeigen wir statt des Widgets nur einen Platzhalter - der Eintausch laeuft
            im Hintergrund trotzdem (siehe useEffect oben), damit der Rest des Formulars unveraendert
            bleibt. */}
        <div className={`captcha-card${captchaReady ? " captcha-card-ok" : ""}`}>
          {sitekey && !captchaReady && (
            <CaptchaWidget key={captchaKey} sitekey={sitekey} onSolved={handleSolved} onExpired={() => { exchangedSolutionRef.current = null; }} />
          )}
          <div className="captcha-status-row">
            <span className="captcha-check" aria-hidden="true">
              {captchaReady && (
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3"><path d="M5 13l4 4L19 7" /></svg>
              )}
            </span>
            <span className="captcha-text">
              <span className="captcha-title">{t("captchaTitle")}</span>
              <span className="captcha-status">
                {!sitekey
                  ? t("captchaPlaceholder")
                  : captchaReady
                    ? t("captchaDone")
                    : captchaVerifying
                      ? t("captchaVerifying")
                      : t("captchaRunning")}
              </span>
            </span>
          </div>
        </div>

        <div className="upload-submit-bar">
          <button type="submit" className="button upload-submit" disabled={submitDisabled}>
            {submitting
              ? t("submitting")
              : files.length > 0
                ? t("submitCount", { count: files.length })
                : t("submit")}
          </button>
        </div>
      </div>
    </form>
  );
}

function fileExtension(name: string): string {
  const parts = name.split(".");
  return parts.length > 1 ? (parts.pop() ?? "").toUpperCase().slice(0, 4) : "";
}

// Farbton des Dateityp-Kaestchens: PDF rot, Word blau, Bilder/Tabellen gruen, sonst neutral.
function extensionTone(ext: string): "danger" | "info" | "success" | "neutral" {
  if (ext === "PDF") return "danger";
  if (ext === "DOC" || ext === "DOCX" || ext === "ODT") return "info";
  if (["JPG", "JPEG", "PNG", "HEIC", "HEIF", "WEBP", "GIF", "XLS", "XLSX", "CSV", "ODS"].includes(ext)) return "success";
  return "neutral";
}
