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
