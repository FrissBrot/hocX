// Analyse einer einzelnen Datei: SHA-256 über die unveränderten Originalbytes plus Metadaten.
// Die Datei wird genau einmal eingelesen - derselbe Puffer dient Hash und Metadatenparser.
// Läuft im Web Worker (image-analysis.worker.ts) oder, wo kein Worker verfügbar ist, im
// Hauptthread (pool.ts).

import { detectImageFormat, ImageFormat, parseImageMetadata, ParsedImageMetadata } from "./metadata";

// Grössere Dateien werden nicht im Browser gehasht (Speicher): sie gehen ohne Vorab-Abgleich
// hoch, der Server prüft sie wie bisher selbst.
export const MAX_ANALYSIS_BYTES = 512 * 1024 ** 2;

export type FileKind = "image" | "zip" | "clip" | "other";

// present: echtes Aufnahmedatum gefunden · missing: Datei geprüft, kein Datum · unknown: nicht prüfbar
export type CaptureDateState = "present" | "missing" | "unknown";

export type FileAnalysis = {
  kind: FileKind;
  // null, wenn kein Hash berechnet werden konnte (zu gross, kein crypto.subtle, Lesefehler).
  sha256: string | null;
  analysis: "ok" | "unsupported" | "failed";
  format: ImageFormat | null;
  captureDate: CaptureDateState;
  metadata: ParsedImageMetadata;
};

export type AnalyzableFile = Pick<File, "name" | "size" | "type" | "arrayBuffer">;

export function fileKind(name: string): FileKind {
  const lower = name.toLowerCase();
  if (lower.endsWith(".zip")) return "zip";
  if (/\.(mov|mp4|m4v)$/.test(lower)) return "clip";
  return "image";
}

function toHex(buffer: ArrayBuffer): string {
  return Array.from(new Uint8Array(buffer), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export async function sha256Hex(buffer: ArrayBuffer): Promise<string | null> {
  const subtle = globalThis.crypto?.subtle;
  if (!subtle) return null; // z. B. kein sicherer Kontext (http) - Fallback auf normalen Upload
  return toHex(await subtle.digest("SHA-256", buffer));
}

export async function analyzeFile(file: AnalyzableFile): Promise<FileAnalysis> {
  const kind = fileKind(file.name);
  const result: FileAnalysis = { kind, sha256: null, analysis: "unsupported", format: null, captureDate: "unknown", metadata: {} };
  // ZIP-Inhalte und Live-Clips prüft ausschliesslich der Server.
  if (kind !== "image" || file.size > MAX_ANALYSIS_BYTES) return result;
  let buffer: ArrayBuffer;
  try {
    buffer = await file.arrayBuffer();
    result.sha256 = await sha256Hex(buffer);
  } catch {
    return { ...result, analysis: "failed" };
  }
  try {
    const bytes = new Uint8Array(buffer);
    result.format = detectImageFormat(bytes);
    if (!result.format) return result;
    result.metadata = parseImageMetadata(bytes, result.format);
    result.analysis = "ok";
    result.captureDate = result.metadata.taken_at ? "present" : "missing";
  } catch {
    // Metadaten unlesbar: nicht behaupten, das Datum fehle - der Server entscheidet.
    result.analysis = "failed";
    result.captureDate = "unknown";
    result.metadata = {};
  }
  return result;
}
