// Lokale Textentwürfe des Protokoll-Editors (localStorage über lib/offline-store).
// Neben dem Entwurf wird der Serverstand gespeichert, auf dem er beruht (Baseline). Hat
// inzwischen jemand anderes den Text geändert, wird der Entwurf beim Öffnen nicht mehr
// stillschweigend übernommen - sonst überschrieb die nächste Speicherung die fremde Fassung
// ohne Vergleich (Audit 2026-11, Protokolle).

export function textDraftKey(blockId: string): string {
  return `protocol-text:${blockId}`;
}

export function textDraftBaseKey(blockId: string): string {
  return `protocol-text-base:${blockId}`;
}

export type DraftRestoreDecision = "none" | "restore" | "conflict";

export function decideDraftRestore(draft: string | null, base: string | null, serverText: string): DraftRestoreDecision {
  if (draft === null || draft === serverText) return "none";
  // Ältere Entwürfe ohne Baseline: wie bisher übernehmen.
  if (base !== null && base !== serverText) return "conflict";
  return "restore";
}
