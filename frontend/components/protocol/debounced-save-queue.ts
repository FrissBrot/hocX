// Entprellte Speicherungen pro Schlüssel (z. B. Textblock) mit Reihenfolge-Garantie und
// «Jetzt alles speichern und abwarten». Wird vom Protokoll-Editor verwendet, damit
// «Protokoll abschliessen» erst nach der letzten Text-Speicherung den Status wechselt
// (Audit 2026-11, Protokolle: der verzögerte PUT kam sonst nach dem PATCH auf
// «abgeschlossen» an und scheiterte mit 409; der letzte Satz fehlte im PDF).

/** Liefert true, wenn der Wert sicher gespeichert (oder durch einen neueren ersetzt) wurde. */
export type SaveSender<T> = (key: string, value: T) => Promise<boolean>;

export type DebouncedSaveQueue<T> = {
  /** Plant die Speicherung von `value` für `key` nach Ablauf der Wartezeit. */
  schedule: (key: string, value: T) => void;
  /** Löst alle wartenden Speicherungen sofort aus und wartet, bis alle laufenden fertig sind. */
  flushAll: () => Promise<boolean>;
  /** Verwirft wartende Timer (z. B. beim Verlassen der Seite). */
  cancelAll: () => void;
  /** true, solange eine Speicherung wartet oder läuft. */
  hasPending: () => boolean;
};

export function createDebouncedSaveQueue<T>(delayMs: number, send: SaveSender<T>): DebouncedSaveQueue<T> {
  const timers = new Map<string, ReturnType<typeof setTimeout>>();
  const waiting = new Map<string, T>();
  const chains = new Map<string, Promise<boolean>>();
  let running = 0;

  const start = (key: string, value: T) => {
    const previous = chains.get(key) ?? Promise.resolve(true);
    running += 1;
    const next = previous
      .then(() => send(key, value))
      .catch(() => false)
      .finally(() => {
        running -= 1;
      });
    chains.set(key, next);
  };

  return {
    schedule(key, value) {
      const timer = timers.get(key);
      if (timer !== undefined) clearTimeout(timer);
      waiting.set(key, value);
      timers.set(
        key,
        setTimeout(() => {
          timers.delete(key);
          if (!waiting.has(key)) return;
          const latest = waiting.get(key) as T;
          waiting.delete(key);
          start(key, latest);
        }, delayMs)
      );
    },
    async flushAll() {
      for (const [key, value] of Array.from(waiting.entries())) {
        const timer = timers.get(key);
        if (timer !== undefined) clearTimeout(timer);
        timers.delete(key);
        waiting.delete(key);
        start(key, value);
      }
      // Pro Schlüssel zählt nur das Ergebnis der jüngsten Speicherung: Ist eine ältere
      // gescheitert, die neuere aber gelungen, ist der aktuelle Text sicher auf dem Server.
      const results = await Promise.all(Array.from(chains.values()));
      return results.every(Boolean);
    },
    cancelAll() {
      for (const timer of Array.from(timers.values())) clearTimeout(timer);
      timers.clear();
      waiting.clear();
    },
    hasPending() {
      return waiting.size > 0 || running > 0;
    },
  };
}
