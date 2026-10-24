// Zählt Upload-Ergebnisse je Datei für die Zusammenfassung ("24 Bilder verarbeitet: 12
// hochgeladen, 8 übersprungen, 4 übersprungen und Metadaten ergänzt"). Jede Datei zählt genau
// einmal: "Metadaten ergänzt" ist ein eigener Status und nie zusätzlich "übersprungen".

import { UploadFileResult } from "@/types/api";

export type UploadResultCounts = { total: number; uploaded: number; skipped: number; metadataUpdated: number; failed: number };

export function countUploadResults(results: UploadFileResult[]): UploadResultCounts {
  const counts: UploadResultCounts = { total: results.length, uploaded: 0, skipped: 0, metadataUpdated: 0, failed: 0 };
  for (const result of results) {
    if (result.status === "uploaded") counts.uploaded++;
    else if (result.status === "skipped") counts.skipped++;
    else if (result.status === "metadata_updated") counts.metadataUpdated++;
    else counts.failed++;
  }
  return counts;
}

/** Nur tatsächlich gespeicherte Ergänzungen - ein "metadata_updated" ohne Felder gilt als
 * übersprungen, damit nie eine Änderung behauptet wird, die nicht stattfand. */
export function normalizeResult(result: UploadFileResult): UploadFileResult {
  if (result.status === "metadata_updated" && !(result.applied?.length)) return { ...result, status: "skipped" };
  return result;
}

/** Ältere Server ohne file_results: Ergebnis aus importierten Dateien und Fehlertexten ableiten. */
export function resultsFromLegacyJob(importedNames: string[], errors: string[]): UploadFileResult[] {
  const results: UploadFileResult[] = importedNames.map((name) => ({ name, status: "uploaded" }));
  for (const error of errors) {
    const [name] = error.split(": ");
    if (error.includes("Exaktes Duplikat")) results.push({ name, status: "skipped" }); // i18n-ok: Serverkennung, kein UI-Text
    else if (!error.includes("ähnelt") && !error.includes("Live-Photo")) results.push({ name, status: "failed", message: error }); // i18n-ok: Serverkennung
  }
  return results;
}

/** Reine Hinweise eines Auftrags (z. B. "ähnelt einem vorhandenen Bild") für den Toast: alle
 * Fehlertexte von Dateien, die nicht hochgeladen wurden, stehen bereits in der Ergebnisliste
 * (übersprungen/fehlgeschlagen). Zuordnung über den Dateinamen-Präfix statt über Servertexte,
 * damit Textänderungen im Backend die Zuordnung nicht still brechen. */
export function jobHintMessages(errors: string[], results: UploadFileResult[]): string[] {
  if (!results.length) return [];
  const listed = results.filter((result) => result.status !== "uploaded").map((result) => `${result.name}: `);
  return errors.filter((error) => !listed.some((prefix) => error.startsWith(prefix)));
}

/** Teilt eine Auswahl in Upload-Batches (Server: max. 50 Dateien je Auftrag, gezählt werden alle
 * Multipart-Dateien inkl. Live-Photo-Clips). Ein Clip bleibt im Batch seines Bildes und zählt
 * mit; ZIPs zählen als je eine Datei. */
export function splitIntoBatches<T>(items: T[], clipOf: Map<number, number>, maxFiles: number, maxBytes: number, size: (item: T) => number): number[][] {
  const clipIndexes = new Set(clipOf.values());
  const batches: number[][] = [];
  let current: number[] = [];
  let currentBytes = 0;
  items.forEach((item, index) => {
    if (clipIndexes.has(index)) return;
    const group = clipOf.has(index) ? [index, clipOf.get(index)!] : [index];
    const groupBytes = group.reduce((sum, member) => sum + size(items[member]), 0);
    if (current.length && (current.length + group.length > maxFiles || currentBytes + groupBytes > maxBytes)) {
      batches.push(current);
      current = [];
      currentBytes = 0;
    }
    current.push(...group);
    currentBytes += groupBytes;
  });
  if (current.length) batches.push(current);
  return batches;
}
