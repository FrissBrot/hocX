// Automatische Wiederholung eines Uploads bei 503 "ausgelastet" (Concurrency-Audit CONC-007):
// Server antwortet mit Retry-After, das Formular sendet die gewählten Dateien selbst erneut.
export const MAX_BUSY_RETRIES = 3;

/** Wartezeit aus dem Retry-After-Header (Sekunden), begrenzt auf 3–30 s, sonst 10 s. */
export function retryDelaySeconds(header: string | null): number {
  const value = Number(header);
  return header !== null && Number.isFinite(value) && value > 0 ? Math.min(30, Math.max(3, Math.round(value))) : 10;
}

/** Nur "ausgelastet" wird wiederholt, Wartung nicht (dafür gibt es das Wartungsbanner). */
export function isRetryableBusy(status: number, code: unknown): boolean {
  return status === 503 && code !== "maintenance";
}
