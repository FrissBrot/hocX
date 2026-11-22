"use client";

import { useTranslations } from "next-intl";

// Ausgewählte Dateien vor dem Absenden. Jeder Entfernen-Knopf nennt seine Datei im
// zugänglichen Namen - sonst hört ein Screenreader bei mehreren Dateien nur «Entfernen,
// Entfernen, Entfernen» und weiss nicht, welche Datei er wegnimmt.
export function UploadFileList({ files, onRemove }: { files: File[]; onRemove: (index: number) => void }) {
  const t = useTranslations("abgabebox.upload");
  if (files.length === 0) return null;
  return (
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
            <button type="button" className="file-remove" onClick={() => onRemove(i)} aria-label={t("removeFile", { filename: file.name })}>✕</button>
          </li>
        );
      })}
    </ul>
  );
}

// Fehlermeldung des Formulars: role="alert", damit Screenreader eine abgelehnte Auswahl
// (falscher Typ, zu gross, zu viele Dateien) oder einen fehlgeschlagenen Upload ansagen.
export function UploadErrorMessage({ message }: { message: string | null }) {
  if (!message) return null;
  return <p className="error" role="alert">{message}</p>;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
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
