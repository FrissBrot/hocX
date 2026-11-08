// Asynchrone Änderungen am selben Objekt nacheinander ausführen: jede wartet, bis die vorige
// (erfolgreich oder nicht) fertig ist. Verhindert, dass parallel abgeschickte Speicherungen sich
// auf dem Server oder beim Übernehmen der Antwort überholen.

const pendingByKey = new Map<string, Promise<unknown>>();

export function runSerializedByKey<T>(key: string, change: () => Promise<T>): Promise<T> {
  const previous = pendingByKey.get(key) ?? Promise.resolve();
  const next = previous.catch(() => undefined).then(change);
  const settled = next.catch(() => undefined);
  pendingByKey.set(key, settled);
  void settled.then(() => {
    if (pendingByKey.get(key) === settled) pendingByKey.delete(key);
  });
  return next;
}
