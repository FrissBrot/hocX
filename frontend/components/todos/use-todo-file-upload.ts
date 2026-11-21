"use client";

import { useCallback, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { useChoice } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch, browserApiUpload } from "@/lib/api/client";
import { hashForPrecheck } from "@/lib/image-analysis/precheck";
import { formatDate } from "@/lib/utils/format";
import type { DocumentUploadResult, FileOverviewItem, TodoDetailFile } from "@/types/api";

const IMAGE_EXTENSIONS = [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff"];

export type TodoUploadPending = { key: string; name: string };

type DuplicateCheckResponse = { matches: { sha256: string; file: FileOverviewItem }[] };

function isImageName(name: string): boolean {
  const dot = name.lastIndexOf(".");
  return dot !== -1 && IMAGE_EXTENSIONS.includes(name.slice(dot).toLowerCase());
}

export function toTodoFile(file: Pick<FileOverviewItem, "id" | "original_name" | "mime_type" | "file_size_bytes" | "content_url">): TodoDetailFile {
  return { id: file.id, original_name: file.original_name, mime_type: file.mime_type, file_size_bytes: file.file_size_bytes, content_url: file.content_url };
}

/**
 * Dateien aus dem Pendenz-Dialog (Drag-and-Drop oder «Datei hochladen …») in die Ablage laden und
 * an den Entwurf der Pendenz hängen. Je Datei, nacheinander:
 *  1. SHA-256 im Browser, POST /api/files/duplicate-check - der Server meldet nur Dateien, die die
 *     Person auch in der Dateisuche sieht (eigener Mandant, Leserechte).
 *  2. Treffer → Rückfrage «Bestehende anhängen» (Standard) | «Kopie hochladen» | Abbrechen.
 *  3. Upload über den Dokument-Upload der Ablage (Grössenlimit, Magic-Byte, ClamAV) mit
 *     allow_duplicates: eine für die Person unsichtbare gleiche Datei wird so nie verraten, es
 *     entsteht eine eigene Kopie. Bilder nur mit photos.manage (allow_images).
 * Gespeichert wird die Verknüpfung wie bei der Dateisuche erst mit «Speichern»/«Erstellen».
 */
export function useTodoFileUpload({ attachedIds, onAttach, canUploadImages }: {
  attachedIds: string[];
  onAttach: (file: TodoDetailFile) => void;
  canUploadImages: boolean;
}) {
  const t = useTranslations("todos");
  const choose = useChoice();
  const showToast = useToast();
  const [pending, setPending] = useState<TodoUploadPending[]>([]);
  // Aktuelle Werte für die laufende Warteschlange (mehrere Dateien nacheinander)
  const attachedRef = useRef(attachedIds);
  attachedRef.current = attachedIds;
  const onAttachRef = useRef(onAttach);
  onAttachRef.current = onAttach;
  const queueRef = useRef(Promise.resolve());

  const processOne = useCallback(async (file: File) => {
    const analysis = await hashForPrecheck(file);
    if (analysis.sha256) {
      let match: FileOverviewItem | undefined;
      try {
        const response = await browserApiFetch<DuplicateCheckResponse>("/api/files/duplicate-check", {
          method: "POST",
          body: JSON.stringify({ sha256: [analysis.sha256] }),
        });
        match = response?.matches[0]?.file;
      } catch {
        // Prüfung nicht möglich: normal (als eigene Datei) hochladen
        match = undefined;
      }
      if (match) {
        if (attachedRef.current.includes(match.id)) {
          showToast(t("fileDrop.alreadyAttached", { name: match.original_name }), "info");
          return;
        }
        const place = match.ref_label || match.origin_tag;
        const choice = await choose({
          title: t("fileDrop.duplicateTitle"),
          message: place
            ? t("fileDrop.duplicateMessage", { name: match.original_name, place, date: formatDate(match.created_at) })
            : t("fileDrop.duplicateMessageNoPlace", { name: match.original_name, date: formatDate(match.created_at) }),
          confirmLabel: t("fileDrop.attachExisting"),
          alternativeLabel: t("fileDrop.uploadCopy"),
        });
        if (choice === "cancel") return;
        if (choice === "confirm") {
          onAttachRef.current(toTodoFile(match));
          showToast(t("fileDrop.attachedExisting", { name: match.original_name }), "success");
          return;
        }
      }
    }
    const key = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    setPending((current) => [...current, { key, name: file.name }]);
    try {
      const body = new FormData();
      body.append("files", file);
      body.append("allow_duplicates", "true");
      if (canUploadImages && isImageName(file.name)) body.append("allow_images", "true");
      const result = await browserApiUpload<DocumentUploadResult>("/api/files/document-uploads", body, { timeoutMs: 300_000 });
      const saved = result?.items[0];
      if (saved) {
        onAttachRef.current(toTodoFile(saved));
        showToast(t("fileDrop.uploaded", { name: saved.original_name }), "success");
      } else {
        showToast(result?.errors.join(" · ") || t("fileDrop.uploadFailed", { name: file.name }), "error");
      }
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("fileDrop.uploadFailed", { name: file.name }), "error");
    } finally {
      setPending((current) => current.filter((entry) => entry.key !== key));
    }
  }, [canUploadImages, choose, showToast, t]);

  /** Mehrere Dateien: alle nacheinander (eine Rückfrage nach der anderen). */
  const uploadFiles = useCallback((files: File[]) => {
    for (const file of files) {
      queueRef.current = queueRef.current.then(() => processOne(file)).catch(() => undefined);
    }
    return queueRef.current;
  }, [processOne]);

  return { pending, uploadFiles };
}
