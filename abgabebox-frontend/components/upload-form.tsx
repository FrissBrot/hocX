"use client";

import { ChangeEvent, DragEvent, FormEvent, useCallback, useRef, useState } from "react";

import { CaptchaWidget } from "@/components/captcha-widget";
import { publicApiUrl } from "@/lib/api";
import { validateUploadFiles } from "@/lib/validate-upload";

type Props = {
  tenantSlug: string;
  assignmentSlug: string;
  elementRef: string;
  allowedFileTypes: string[];
  maxFiles: number | null;
  maxFileSizeMb: number;
  alreadyUploadedCount: number;
  sitekey: string;
};

export function UploadForm({ tenantSlug, assignmentSlug, elementRef, allowedFileTypes, maxFiles, maxFileSizeMb, alreadyUploadedCount, sitekey }: Props) {
  const [files, setFiles] = useState<File[]>([]);
  const [dragging, setDragging] = useState(false);
  const [captchaSessionToken, setCaptchaSessionToken] = useState<string | null>(null);
  const [captchaVerifying, setCaptchaVerifying] = useState(false);
  const [captchaKey, setCaptchaKey] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [done, setDone] = useState(false);
  const [uploadedSoFar, setUploadedSoFar] = useState(alreadyUploadedCount);
  const inputRef = useRef<HTMLInputElement>(null);
  // Welche rohe FriendlyCaptcha-Loesung bereits gegen ein Sitzungs-Token eingetauscht wurde -
  // handleSolved kann mehrfach mit derselben Loesung feuern (Callback + DOM-Fallback im Widget).
  const exchangedSolutionRef = useRef<string | null>(null);

  const accept = allowedFileTypes.length > 0 ? allowedFileTypes.map((t) => `.${t}`).join(",") : undefined;
  const typeLabel = allowedFileTypes.length > 0 ? allowedFileTypes.map((t) => t.toUpperCase()).join(", ") : "Alle Dateitypen";
  const remaining = maxFiles === null ? null : Math.max(0, maxFiles - uploadedSoFar);

  function validateAndSet(selected: File[]): boolean {
    const result = validateUploadFiles(selected, { maxFiles, allowedFileTypes, maxFileSizeMb, alreadyUploaded: uploadedSoFar });
    if (!result.ok) {
      setError(result.error);
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
        publicApiUrl(`/api/public/${tenantSlug}/assignments/${assignmentSlug}/elements/${elementRef}/captcha-verify`),
        { method: "POST", body: formData }
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
  }, [tenantSlug, assignmentSlug, elementRef]);

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
    if (files.length === 0) { setError("Bitte mindestens eine Datei auswählen"); return; }

    if (!captchaSessionToken) {
      setError("Sicherheitscheck läuft noch – bitte kurz warten und nochmals versuchen");
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
        publicApiUrl(`/api/public/${tenantSlug}/assignments/${assignmentSlug}/elements/${elementRef}/upload`),
        { method: "POST", body: formData }
      );
      if (!response.ok) {
        if (response.status === 429) {
          throw new Error("Zu viele Versuche – bitte kurz warten und dann nochmals versuchen");
        }
        if (response.status === 401) {
          // Sitzungs-Token abgelaufen (siehe ABGABEBOX_CAPTCHA_SESSION_TTL_MINUTES) - Widget fuer
          // eine frische Loesung neu starten, ausgewaehlte Dateien bleiben erhalten.
          requestFreshCaptcha();
          throw new Error("Sicherheitscheck ist abgelaufen – wird gerade erneuert, bitte kurz warten");
        }
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail ?? "Upload fehlgeschlagen");
      }
      const result = await response.json().catch(() => null);
      setWarnings(result?.image_duplicate_warnings ?? []);
      setUploadedSoFar((prev) => prev + files.length);
      setFiles([]);
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload fehlgeschlagen");
    } finally {
      // Das Sitzungs-Token bleibt bewusst erhalten (ausser beim 401-Fall oben) - der
      // Sicherheitscheck soll nur einmal pro Seitenaufruf laufen, nicht vor jedem Upload.
      setSubmitting(false);
    }
  }

  const remainingAfterSuccess = maxFiles === null ? null : Math.max(0, maxFiles - uploadedSoFar);
  const canUploadMore = remainingAfterSuccess === null || remainingAfterSuccess > 0;

  if (done) {
    return (
      <div className="upload-success">
        <div className="upload-success-icon">✓</div>
        <div className="upload-success-title">Abgabe erfolgreich</div>
        <div className="upload-success-sub">
          {uploadedSoFar} Datei{uploadedSoFar === 1 ? "" : "en"} für diese Abgabe hochgeladen.
        </div>
        {warnings.length > 0 && (
          <div className="upload-warning-list">
            {warnings.map((warning, i) => (
              <p key={i}>{warning}</p>
            ))}
          </div>
        )}
        {canUploadMore && (
          <button type="button" className="button" style={{ marginTop: 16 }} onClick={() => setDone(false)}>
            Weitere Datei hochladen
          </button>
        )}
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit}>
      {uploadedSoFar > 0 && (
        <p className="upload-already-count">
          Bereits {uploadedSoFar} Datei{uploadedSoFar === 1 ? "" : "en"} für diese Abgabe hochgeladen.
        </p>
      )}

      {/* Drop zone */}
      <div
        className={`drop-zone${dragging ? " drop-zone-active" : ""}${files.length > 0 ? " drop-zone-filled" : ""}`}
        onClick={() => inputRef.current?.click()}
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
        <div className="drop-zone-icon">{files.length > 0 ? "📄" : "⬆"}</div>
        <div className="drop-zone-label">
          {files.length > 0
            ? `${files.length} Datei${files.length > 1 ? "en" : ""} ausgewählt`
            : "Datei auswählen oder hierher ziehen"}
        </div>
        <div className="drop-zone-hint">
          {typeLabel} · {remaining === null ? "beliebig viele Dateien" : `max. ${remaining} weitere ${remaining === 1 ? "Datei" : "Dateien"}`} · je {maxFileSizeMb} MB
        </div>
      </div>

      {/* File list */}
      {files.length > 0 && (
        <ul className="file-list">
          {files.map((file, i) => (
            <li key={i} className="file-item">
              <span className="file-name">{file.name}</span>
              <span className="file-size">{formatSize(file.size)}</span>
              <button type="button" className="file-remove" onClick={() => removeFile(i)} aria-label="Entfernen">✕</button>
            </li>
          ))}
        </ul>
      )}

      {/* Captcha - laeuft einmal beim Laden der Seite, bleibt danach fuer alle weiteren Uploads
          gueltig (siehe handleSolved oben) - das Widget selbst wird nach erfolgreichem Eintausch
          ausgeblendet, nur der Status bleibt sichtbar. */}
      {sitekey && (
        <div style={{ margin: "20px 0 4px" }}>
          {!captchaSessionToken && (
            <CaptchaWidget key={captchaKey} sitekey={sitekey} onSolved={handleSolved} onExpired={() => { exchangedSolutionRef.current = null; }} />
          )}
          <div className={`captcha-status${captchaSessionToken ? " captcha-status-ok" : ""}`}>
            {captchaSessionToken
              ? "✓ Sicherheitscheck abgeschlossen"
              : captchaVerifying
                ? "Sicherheitscheck wird geprüft…"
                : "Sicherheitscheck läuft…"}
          </div>
        </div>
      )}

      {error && <p className="error">{error}</p>}

      <button
        type="submit"
        className="button"
        style={{ width: "100%", marginTop: 12 }}
        disabled={submitting || files.length === 0}
      >
        {submitting ? "Wird hochgeladen…" : "Abgeben"}
      </button>
    </form>
  );
}
