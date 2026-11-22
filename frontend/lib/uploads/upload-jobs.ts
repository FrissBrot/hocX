// Upload-Verlauf (Backend: routes/upload_jobs.py, Migration 0250). Ein Vorgang fasst alles zusammen,
// was die Person als *einen* Upload erlebt: Vorab-Abgleich, alle Pakete, vom Browser abgelehnte
// Dateien. Fehlt der Vorgang (älteres Backend, Netzfehler), läuft der Upload trotzdem - der Server
// legt dann je Request einen eigenen Vorgang an.

import { browserApiFetch } from "@/lib/api/client";
import type { UploadChannel, UploadJob } from "@/types/api";

export type UploadJobTarget = {
  event_id?: string | null;
  submission_assignment_id?: string | null;
  submission_element_ref?: string | null;
  cycle_config_id?: string | null;
  protocol_todo_id?: string | null;
};

/** Bezug aus den Formularfeldern des Upload-Ziels (useUploadTarget().appendTo) für POST /upload-jobs. */
export function targetFromForm(append: (form: FormData) => void): UploadJobTarget {
  const form = new FormData();
  append(form);
  const value = (key: string) => {
    const entry = form.get(key);
    return typeof entry === "string" && entry ? entry : null;
  };
  return {
    event_id: value("event_id"),
    submission_assignment_id: value("submission_assignment_id"),
    submission_element_ref: value("submission_element_ref"),
    cycle_config_id: value("cycle_config_id"),
  };
}

export async function openUploadJob(
  channel: Extract<UploadChannel, "gallery" | "document" | "todo">,
  options: UploadJobTarget & { tags?: string[]; estimated_taken_on?: string | null; include_gps?: boolean } = {},
): Promise<string | null> {
  try {
    const job = await browserApiFetch<UploadJob>("/api/upload-jobs", {
      method: "POST",
      body: JSON.stringify({ channel, ...options }),
    });
    return job?.id ?? null;
  } catch {
    return null;
  }
}

/** Best effort: der Server schliesst verlassene Vorgänge nach 24 h selbst. */
export async function completeUploadJob(id: string | null): Promise<void> {
  if (!id) return;
  try {
    await browserApiFetch(`/api/upload-jobs/${id}/complete`, { method: "POST" });
  } catch {
    // ignorieren
  }
}

export type ClientRejection = { name: string; size?: number | null; code?: "too_large" | "unsupported_format" | "rule_violation" | "heic_unreadable" | "client_rejected" };

/** Vom Browser vor dem Senden abgelehnte Dateien melden (E-14), höchstens 500 je Aufruf. */
export async function reportClientRejections(id: string | null, rejections: ClientRejection[]): Promise<void> {
  if (!id || rejections.length === 0) return;
  for (let start = 0; start < rejections.length; start += 500) {
    const chunk = rejections.slice(start, start + 500);
    try {
      await browserApiFetch(`/api/upload-jobs/${id}/client-results`, {
        method: "POST",
        body: JSON.stringify({ items: chunk.map((entry) => ({ name: entry.name.slice(0, 500), size: entry.size ?? null, code: entry.code ?? "client_rejected" })) }),
      });
    } catch {
      return;
    }
  }
}

export type ChunkProgress = { done: number; total: number };

export type ChunkOutcome<R> = { results: R[]; failedChunks: number; cancelled: boolean; firstError?: unknown };

/**
 * Bulk-Aktion in Stücken (E-4): sequenziell, je Stück eine eigene Transaktion auf dem Server.
 * Teilerfolge bleiben bestehen; ein Fehler bricht nicht ab, sondern zählt als fehlgeschlagenes Stück.
 * `shouldCancel` wird vor jedem Stück abgefragt.
 */
export async function runInChunks<T, R>(
  items: T[],
  size: number,
  run: (chunk: T[], index: number) => Promise<R>,
  options: { onProgress?: (progress: ChunkProgress) => void; shouldCancel?: () => boolean } = {},
): Promise<ChunkOutcome<R>> {
  const results: R[] = [];
  let failedChunks = 0;
  let firstError: unknown;
  let done = 0;
  options.onProgress?.({ done, total: items.length });
  for (let start = 0, index = 0; start < items.length; start += size, index += 1) {
    if (options.shouldCancel?.()) return { results, failedChunks, cancelled: true, firstError };
    const chunk = items.slice(start, start + size);
    try {
      results.push(await run(chunk, index));
    } catch (error) {
      failedChunks += 1;
      firstError ??= error;
    }
    done += chunk.length;
    options.onProgress?.({ done, total: items.length });
  }
  return { results, failedChunks, cancelled: false, firstError };
}

const DISMISSED_KEY = "hocx.uploadHint.dismissed";

/** Hinweisstreifen «… hochgeladen – bearbeiten»: pro Vorgang ausblendbar (localStorage, try/catch). */
export function isUploadHintDismissed(id: string): boolean {
  try {
    const raw = window.localStorage.getItem(DISMISSED_KEY);
    return raw ? (JSON.parse(raw) as string[]).includes(id) : false;
  } catch {
    return false;
  }
}

export function dismissUploadHint(id: string): void {
  try {
    const raw = window.localStorage.getItem(DISMISSED_KEY);
    const list = raw ? (JSON.parse(raw) as string[]) : [];
    window.localStorage.setItem(DISMISSED_KEY, JSON.stringify([id, ...list.filter((entry) => entry !== id)].slice(0, 50)));
  } catch {
    // ohne Speicher bleibt der Hinweis bis zum Neuladen ausgeblendet
  }
}

/** Kanäle je Bereich (Verlauf der Fotos bzw. der Ablage). Protokollbilder nur auf ausdrücklichen Filter. */
export const PHOTO_CHANNELS: UploadChannel[] = ["gallery", "cloud_import", "todo", "abgabebox", "submission_link", "tenant_import"];
export const FILE_CHANNELS: UploadChannel[] = ["document", "todo", "word_import", "cloud_import", "abgabebox", "submission_link", "tenant_import"];
export const ALL_CHANNELS: UploadChannel[] = [
  "gallery", "document", "todo", "cloud_import", "abgabebox", "submission_link", "word_import", "protocol_image", "tenant_import",
];
