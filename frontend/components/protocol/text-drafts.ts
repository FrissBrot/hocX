// Lokale Textentwürfe des Protokoll-Editors (localStorage über lib/offline-store).
// Neben dem Entwurf wird der Serverstand gespeichert, auf dem er beruht (Baseline). Hat
// inzwischen jemand anderes den Text geändert, wird der Entwurf beim Öffnen nicht mehr
// stillschweigend übernommen - sonst überschrieb die nächste Speicherung die fremde Fassung
// ohne Vergleich (Audit 2026-11, Protokolle).
//
// Schnelles Neuladen (1.6): Lädt die Seite neu, nachdem der Server gespeichert, die Antwort aber
// noch nicht ankam, bleibt ein Entwurf liegen, der dem Serverstand entspricht ("saved"). Er wird
// beim Öffnen entfernt; sonst stellte ihn ein späteres Öffnen über eine inzwischen neuere Fassung
// (Sitzungsnotizen ohne Baseline) bzw. hielt die nächste Eingabe für einen Konflikt. Und landet
// eine Speicherung, während schon weiter getippt wurde, rückt die Baseline auf den gespeicherten
// Stand nach (settleDraftAfterSave) - sonst galt der neuere Entwurf nach dem Neuladen als Konflikt
// und der ältere Serverstand blieb stehen.

import { clearDraft, readDraft, saveDraft } from "@/lib/offline-store";

export function textDraftKey(blockId: string): string {
  return `protocol-text:${blockId}`;
}

export function textDraftBaseKey(blockId: string): string {
  return `protocol-text-base:${blockId}`;
}

export function notesDraftBaseKey(protocolId: string): string {
  return `protocol-notes-base:${protocolId}`;
}

export type DraftRestoreDecision = "none" | "saved" | "restore" | "conflict";

export function decideDraftRestore(draft: string | null, base: string | null, serverText: string): DraftRestoreDecision {
  if (draft === null) return "none";
  // Schon gespeichert (Neuladen vor der Antwort): nur noch aufräumen
  if (draft === serverText) return "saved";
  // Ältere Entwürfe ohne Baseline: wie bisher übernehmen.
  if (base !== null && base !== serverText) return "conflict";
  return "restore";
}

/** Nach einer vom Server bestätigten Speicherung von ``saved``. Ist der Entwurf noch genau dieser
 * Stand, werden Entwurf und Baseline entfernt (true). Wurde inzwischen weiter getippt, bleibt der
 * neuere Entwurf; seine Baseline ist jetzt der gespeicherte Stand, und ``requeue`` reiht ihn mit
 * dieser Baseline neu in die Outbox ein (false). */
export function settleDraftAfterSave(key: string, baseKey: string, saved: string, requeue: (latest: string) => void): boolean {
  const latest = readDraft(key);
  if (latest === null || latest === saved) {
    clearDraft(key);
    clearDraft(baseKey);
    return true;
  }
  saveDraft(baseKey, saved);
  requeue(latest);
  return false;
}
