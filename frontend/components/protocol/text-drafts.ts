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

/**
 * Aktueller Text je Textblock ausserhalb des React-Zustands des Editors (T3): eine Taste ändert
 * nur diesen Store, neu rendert nur der betroffene Textblock (useTextDraft). Gliederung, Kopf und
 * die übrigen Punkte bleiben unberührt. Wer nur wissen muss, ob Blöcke leer sind (PDF-Abdeckung),
 * abonniert die Leer-Signatur, die sich nur beim Wechsel leer/gefüllt ändert.
 */
export type TextDraftStore = {
  /** undefined: Block noch ohne Entwurf (dann gilt text_content des Blocks) */
  get: (blockId: string) => string | undefined;
  getAll: () => Readonly<Record<string, string>>;
  set: (blockId: string, value: string) => void;
  setMany: (entries: Iterable<readonly [string, string]>) => void;
  subscribe: (blockId: string, listener: () => void) => () => void;
  /** Ändert sich nur, wenn ein Block zwischen leer und gefüllt wechselt. */
  getEmptinessKey: () => string;
  subscribeEmptiness: (listener: () => void) => () => void;
};

function emptinessKeyOf(values: Record<string, string>): string {
  return Object.keys(values)
    .filter((blockId) => !values[blockId]?.trim())
    .sort()
    .join(",");
}

export function createTextDraftStore(initial: Record<string, string>): TextDraftStore {
  let values: Record<string, string> = { ...initial };
  let emptinessKey = emptinessKeyOf(values);
  const listeners = new Map<string, Set<() => void>>();
  const emptinessListeners = new Set<() => void>();

  function notify(blockIds: string[]) {
    for (const blockId of blockIds) listeners.get(blockId)?.forEach((listener) => listener());
    const nextKey = emptinessKeyOf(values);
    if (nextKey !== emptinessKey) {
      emptinessKey = nextKey;
      emptinessListeners.forEach((listener) => listener());
    }
  }

  return {
    get: (blockId) => values[blockId],
    getAll: () => values,
    set(blockId, value) {
      if (values[blockId] === value) return;
      values = { ...values, [blockId]: value };
      notify([blockId]);
    },
    setMany(entries) {
      const changed: string[] = [];
      const next = { ...values };
      for (const [blockId, value] of entries) {
        if (next[blockId] === value) continue;
        next[blockId] = value;
        changed.push(blockId);
      }
      if (!changed.length) return;
      values = next;
      notify(changed);
    },
    subscribe(blockId, listener) {
      let set = listeners.get(blockId);
      if (!set) listeners.set(blockId, (set = new Set()));
      set.add(listener);
      return () => {
        set!.delete(listener);
      };
    },
    getEmptinessKey: () => emptinessKey,
    subscribeEmptiness(listener) {
      emptinessListeners.add(listener);
      return () => {
        emptinessListeners.delete(listener);
      };
    },
  };
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
