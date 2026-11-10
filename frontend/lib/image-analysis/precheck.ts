// Vorab-Abgleich mit dem Server (POST /api/files/upload-precheck): schickt Hashes und Metadaten,
// bevor Dateibytes übertragen werden. Jeder Fehler führt sicher zum normalen Upload zurück -
// der Server erkennt Duplikate beim Upload ohnehin selbst noch einmal.

import { analyzeFile, FileAnalysis, MAX_ANALYSIS_BYTES, sha256Hex } from "./analyze";
import { browserApiFetch } from "@/lib/api/client";
import { MetadataField, UploadFileResult, UploadPrecheckResult } from "@/types/api";

export const PRECHECK_CHUNK_SIZE = 200;

export type PrecheckContext = "gallery" | "document" | "protocol_image";

export type PrecheckEntry = { index: number; file: Pick<File, "name" | "size" | "type">; analysis: FileAnalysis };

/** includeGps=false: «GPS-Daten des Bildes mitsenden» aus (Datenschutz-Audit Paket 9.3). */
export function clientMetadataPayload(analysis: FileAnalysis, includeGps = true) {
  const { taken_at, taken_offset, gps, camera_make, camera_model, width, height, orientation } = analysis.metadata;
  const payload = { taken_at, taken_offset, gps: includeGps ? gps : undefined, camera_make, camera_model, width, height, orientation };
  return Object.values(payload).some((value) => value !== undefined) ? payload : null;
}

/** Ergebnis je Index; Dateien ohne Hash fehlen (sie werden normal hochgeladen). Bei einem
 * Fehler des Endpunkts `null` = alles normal hochladen. */
export async function precheckUploads(
  entries: PrecheckEntry[],
  options: { context: PrecheckContext; estimatedTakenOn?: string | null; signal?: AbortSignal; includeGps?: boolean },
): Promise<Map<number, UploadPrecheckResult> | null> {
  const hashed = entries.filter((entry) => entry.analysis.sha256);
  const results = new Map<number, UploadPrecheckResult>();
  try {
    for (let start = 0; start < hashed.length; start += PRECHECK_CHUNK_SIZE) {
      const chunk = hashed.slice(start, start + PRECHECK_CHUNK_SIZE);
      const response = await browserApiFetch<{ results: UploadPrecheckResult[] }>("/api/files/upload-precheck", {
        method: "POST",
        signal: options.signal,
        body: JSON.stringify({
          context: options.context,
          estimated_taken_on: options.estimatedTakenOn || null,
          files: chunk.map((entry) => ({
            client_id: String(entry.index),
            sha256: entry.analysis.sha256,
            name: entry.file.name.slice(0, 500),
            size: entry.file.size,
            mime_type: entry.file.type ? entry.file.type.slice(0, 100) : null,
            analysis: entry.analysis.analysis,
            metadata: options.context === "gallery" ? clientMetadataPayload(entry.analysis, options.includeGps ?? true) : null,
          })),
        }),
      });
      for (const result of response?.results ?? []) results.set(Number(result.client_id), result);
    }
  } catch (error) {
    if (options.signal?.aborted) throw error;
    return null;
  }
  return results;
}

/** Muss die Datei noch übertragen werden? Nur bei bestätigt vorhandenen Dateien nicht. */
export function needsUpload(result: UploadPrecheckResult | undefined): boolean {
  return !result || result.status === "upload_required" || result.status === "fallback_required";
}

/** Vorab-Ergebnis als Upload-Ergebnis für die gemeinsame Ergebnisanzeige. */
export function precheckToFileResult(name: string, result: UploadPrecheckResult): UploadFileResult {
  return {
    name,
    status: result.status === "metadata_updated" ? "metadata_updated" : "skipped",
    file_id: result.file_id,
    applied: result.applied as MetadataField[],
    conflicts: result.conflicts as MetadataField[],
  };
}

/** Hinweise für das Formularfeld file_metadata des Galerie-Uploads. Nur für HEIC/HEIF: allein
 * dort übernimmt der Server Browser-Werte (Konvertierung nach JPEG). Für alle anderen Formate
 * liest er die Datei selbst - GPS & Co. werden dann gar nicht erst mitgeschickt
 * (Datenminimierung, der Auftrag speichert die Hinweise bis zu seinem Ende). */
export function fileMetadataHints(analyses: FileAnalysis[], includeGps = true): string | null {
  const hints = analyses
    .filter((analysis) => analysis.format === "heic" && analysis.sha256 && clientMetadataPayload(analysis, includeGps))
    .map((analysis) => ({ sha256: analysis.sha256, metadata: clientMetadataPayload(analysis, includeGps) }));
  return hints.length ? JSON.stringify(hints) : null;
}

/** Einzelbild-Variante (Protokollbilder): true, wenn das Bild im Mandanten schon existiert
 * und der Server einen Upload ohnehin als Duplikat ablehnen würde - spart die Übertragung.
 * Jeder Fehler -> false (normal hochladen, der Server prüft selbst). */
export async function isAlreadyUploaded(file: File, context: PrecheckContext): Promise<boolean> {
  try {
    const analysis = await analyzeFile(file);
    if (!analysis.sha256) return false;
    const results = await precheckUploads([{ index: 0, file, analysis }], { context });
    const result = results?.get(0);
    return Boolean(result && !needsUpload(result));
  } catch {
    return false;
  }
}

/** Nur der Hash (Dokumente): kein Metadatenparser, gleiche Grössengrenze wie bei Bildern. */
export async function hashForPrecheck(file: Pick<File, "name" | "size" | "type" | "arrayBuffer">): Promise<FileAnalysis> {
  const base: FileAnalysis = { kind: "other", sha256: null, analysis: "unsupported", format: null, captureDate: "unknown", metadata: {} };
  if (file.size > MAX_ANALYSIS_BYTES) return base;
  try {
    return { ...base, sha256: await sha256Hex(await file.arrayBuffer()), analysis: "ok" };
  } catch {
    return { ...base, analysis: "failed" };
  }
}
