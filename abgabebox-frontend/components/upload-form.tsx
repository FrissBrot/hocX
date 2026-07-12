"use client";

import { ChangeEvent, DragEvent, FormEvent, useRef, useState } from "react";

import { CaptchaWidget } from "@/components/captcha-widget";
import { publicApiUrl } from "@/lib/api";

type Props = {
  tenantSlug: string;
  assignmentSlug: string;
  elementRef: string;
  allowedFileTypes: string[];
  maxFiles: number;
  maxFileSizeMb: number;
  sitekey: string;
};

export function UploadForm({ tenantSlug, assignmentSlug, elementRef, allowedFileTypes, maxFiles, maxFileSizeMb, sitekey }: Props) {
  const [files, setFiles] = useState<File[]>([]);
  const [dragging, setDragging] = useState(false);
  const [captchaSolution, setCaptchaSolution] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const captchaWidgetRef = useRef<HTMLDivElement>(null);

  const accept = allowedFileTypes.length > 0 ? allowedFileTypes.map((t) => `.${t}`).join(",") : undefined;
  const typeLabel = allowedFileTypes.length > 0 ? allowedFileTypes.map((t) => t.toUpperCase()).join(", ") : "Alle Dateitypen";

  function validateAndSet(selected: File[]): boolean {
    if (selected.length > maxFiles) {
      setError(`Maximal ${maxFiles} Datei(en) erlaubt`);
      return false;
    }
    const tooLarge = selected.find((f) => f.size > maxFileSizeMb * 1024 * 1024);
    if (tooLarge) {
      setError(`„${tooLarge.name}" ist zu gross (max. ${maxFileSizeMb} MB)`);
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

  // Try to read the solution directly from the DOM as fallback when callback didn't fire
  function getCaptchaSolution(): string | null {
    if (captchaSolution) return captchaSolution;
    const widget = captchaWidgetRef.current;
    if (!widget) return null;
    // FriendlyCaptcha stores solution in data-response attribute after solving
    const response = widget.getAttribute("data-response");
    if (response && response !== ".") return response;
    return null;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (files.length === 0) { setError("Bitte mindestens eine Datei auswählen"); return; }

    const solution = getCaptchaSolution();
    if (!solution) {
      setError("Sicherheitscheck läuft noch – bitte kurz warten und nochmals versuchen");
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append("captcha_solution", solution);
      files.forEach((file) => formData.append("files", file));
      const response = await fetch(
        publicApiUrl(`/api/public/${tenantSlug}/assignments/${assignmentSlug}/elements/${elementRef}/upload`),
        { method: "POST", body: formData }
      );
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail ?? "Upload fehlgeschlagen");
      }
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload fehlgeschlagen");
    } finally {
      setSubmitting(false);
    }
  }

  if (done) {
    return (
      <div className="upload-success">
        <div className="upload-success-icon">✓</div>
        <div className="upload-success-title">Abgabe erfolgreich</div>
        <div className="upload-success-sub">Deine Datei wurde hochgeladen.</div>
      </div>
    );
  }

  const captchaReady = !!getCaptchaSolution();

  return (
    <form onSubmit={handleSubmit}>
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
          multiple={maxFiles > 1}
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
          {typeLabel} · max. {maxFiles} {maxFiles === 1 ? "Datei" : "Dateien"} · je {maxFileSizeMb} MB
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

      {/* Captcha */}
      {sitekey && (
        <div style={{ margin: "20px 0 4px" }}>
          <CaptchaWidget
            sitekey={sitekey}
            onSolved={(sol) => setCaptchaSolution(sol)}
            onExpired={() => setCaptchaSolution(null)}
            widgetRef={captchaWidgetRef}
          />
          <div className={`captcha-status${captchaReady ? " captcha-status-ok" : ""}`}>
            {captchaReady ? "✓ Sicherheitscheck abgeschlossen" : "Sicherheitscheck läuft…"}
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
