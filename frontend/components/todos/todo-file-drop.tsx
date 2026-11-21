"use client";

import { useCallback, useState } from "react";
import { useTranslations } from "next-intl";

import { FileTypeIcon } from "@/components/files/file-type-icon";
import { useElementFileDrop } from "@/lib/hooks/use-file-drop";
import type { TodoUploadPending } from "./use-todo-file-upload";

/**
 * Das ganze Pendenz-Popup als Dropzone. `anchorRef` kommt an ein beliebiges Element im Dialog
 * (z. B. den Kopf); Ziel ist dessen `.modal-shell`. Liefert `isDragging` für das Overlay.
 */
export function useTodoDialogDropzone(onFiles: (files: File[]) => void, enabled: boolean) {
  const [shell, setShell] = useState<HTMLElement | null>(null);
  const anchorRef = useCallback((element: HTMLElement | null) => {
    setShell(element ? (element.closest(".modal-shell") as HTMLElement | null) : null);
  }, []);
  const isDragging = useElementFileDrop(() => shell, onFiles, enabled && !!shell);
  return { anchorRef, isDragging };
}

/** Overlay «Loslassen zum Anhängen» über dem ganzen Dialog. Rein optisch: pointer-events aus,
 * damit es den Drop nie schluckt; für Screenreader ohne Bedeutung (Tastaturweg: «Datei hochladen …»). */
export function TodoFileDropOverlay({ active }: { active: boolean }) {
  const t = useTranslations("todos");
  if (!active) return null;
  return <div className="todo-drop-overlay" aria-hidden="true" data-testid="todo-drop-overlay">
    <div className="todo-drop-overlay-frame">
      <span className="todo-drop-overlay-icon">
        <svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 16V5m0 0-4 4m4-4 4 4" />
          <path d="M5 15v2.5A1.5 1.5 0 0 0 6.5 19h11a1.5 1.5 0 0 0 1.5-1.5V15" />
        </svg>
      </span>
      <p className="todo-drop-overlay-title">{t("fileDrop.overlayTitle")}</p>
      <p className="todo-drop-overlay-text">{t("fileDrop.overlayText")}</p>
    </div>
  </div>;
}

/** Laufende Uploads als Zeilen in der Dateiliste der Pendenz. */
export function TodoPendingUploadItems({ pending }: { pending: TodoUploadPending[] }) {
  const t = useTranslations("todos");
  return <>
    {pending.map((entry) => <li key={entry.key} className="todo-upload-pending" aria-live="polite">
      <span className="todo-edit-file">
        <FileTypeIcon name={entry.name} />
        <span className="todo-file-name">{entry.name}</span>
        <small className="muted">{t("fileDrop.uploading")}</small>
      </span>
    </li>)}
  </>;
}
