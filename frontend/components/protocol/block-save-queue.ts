// Speicherreihenfolge und Sperrfreigabe je Block (Collaboration-Audit 1.6.1, F-01 und F-04).

/**
 * Führt Aufgaben je Schlüssel strikt nacheinander aus (F-04). Vorher liefen zwei PATCHes derselben
 * Blockkonfiguration parallel mit derselben `expected_config_version` (z. B. Aufzählungspunkt
 * bearbeiten und sofort «+»): der zweite bekam 409, die Änderung ging verloren und der Toast
 * behauptete, jemand anderes habe geändert.
 */
export type SerialQueue = {
  /** Hängt `task` an die Kette von `key` an; das Ergebnis ist das der Aufgabe selbst. */
  run: <T>(key: string, task: () => Promise<T>) => Promise<T>;
  /** Wartet, bis für `key` nichts mehr läuft oder wartet (auch später Angehängtes). */
  whenIdle: (key: string) => Promise<void>;
  /** Anzahl laufender oder wartender Aufgaben für `key`. */
  pending: (key: string) => number;
};

export function createSerialQueue(): SerialQueue {
  const chains = new Map<string, Promise<unknown>>();
  const counts = new Map<string, number>();
  return {
    run<T>(key: string, task: () => Promise<T>): Promise<T> {
      counts.set(key, (counts.get(key) ?? 0) + 1);
      const previous = chains.get(key) ?? Promise.resolve();
      const result = previous.then(task).finally(() => {
        const left = (counts.get(key) ?? 1) - 1;
        if (left <= 0) counts.delete(key);
        else counts.set(key, left);
      });
      const settled = result.then(
        () => undefined,
        () => undefined
      );
      chains.set(key, settled);
      void settled.then(() => {
        if (chains.get(key) === settled) chains.delete(key);
      });
      return result;
    },
    async whenIdle(key: string) {
      for (;;) {
        const chain = chains.get(key);
        if (!chain) return;
        await chain;
        if (chains.get(key) === chain || !chains.has(key)) return;
      }
    },
    pending(key: string) {
      return counts.get(key) ?? 0;
    },
  };
}

/** Block-ID eines Sperrschlüssels (`block-<id>` oder Matrixzelle `block-<id>-cell-…`). */
export function blockIdOfLockKey(fieldKey: string): string | null {
  if (!fieldKey.startsWith("block-")) return null;
  const blockId = fieldKey.slice("block-".length).split("-cell-")[0];
  return blockId || null;
}

export type FieldLockActions = {
  lockField: (fieldKey: string) => void;
  unlockField: (fieldKey: string) => void;
};

/**
 * Sperre erst freigeben, wenn die Speicherungen des Blocks durch sind (F-01).
 *
 * Vorher gab der Editor die Sperre beim Verlassen eines Blocks sofort frei, die entprellte
 * Speicherung (700 ms) und deren `field_update` kamen erst danach. Der Server verwirft ein
 * `field_update` ohne Sperre (`field_update_rejected`), die anderen sahen den zuletzt
 * gespeicherten Text deshalb nie. Jetzt:
 *
 * 1. Freigabe einen Makrotask später: Blur-Speicherungen derselben Ereigniskette (Capture am
 *    Block vor `onBlur` am Feld) sind dann eingeplant.
 * 2. `waitForSaves` löst wartende Speicherungen sofort aus und wartet sie samt `field_update` ab.
 * 3. Erst dann `unlock` - ausser der Schlüssel wurde inzwischen erneut gesperrt (zurück in den
 *    Block): dann bleibt die Sperre stehen.
 */
export function createDeferredUnlock(
  target: FieldLockActions,
  waitForSaves: (fieldKey: string) => Promise<unknown>,
  defer: (callback: () => void) => void = (callback) => {
    setTimeout(callback, 0);
  }
): FieldLockActions {
  const generation = new Map<string, number>();
  return {
    lockField(fieldKey) {
      generation.set(fieldKey, (generation.get(fieldKey) ?? 0) + 1);
      target.lockField(fieldKey);
    },
    unlockField(fieldKey) {
      const requestedAt = generation.get(fieldKey) ?? 0;
      defer(() => {
        void Promise.resolve()
          .then(() => waitForSaves(fieldKey))
          .catch(() => undefined)
          .then(() => {
            if ((generation.get(fieldKey) ?? 0) !== requestedAt) return;
            target.unlockField(fieldKey);
          });
      });
    },
  };
}
