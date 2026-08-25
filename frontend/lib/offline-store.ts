"use client";

export type PendingMutation = {
  id: string;
  key: string;
  path: string;
  method: "PUT" | "PATCH";
  body: string;
  createdAt: number;
  attempts: number;
  lastError?: string;
};

export type OfflineSnapshot = {
  online: boolean;
  pending: number;
  flushing: boolean;
  lastError: string | null;
};

const OUTBOX_KEY = "hocx-offline-outbox-v1";
const DRAFT_PREFIX = "hocx-draft-v1:";
let snapshot: OfflineSnapshot = { online: true, pending: 0, flushing: false, lastError: null };
const serverSnapshot: OfflineSnapshot = { online: true, pending: 0, flushing: false, lastError: null };
const listeners = new Set<() => void>();
let flushTimer: number | null = null;
let retryDelayMs = 1_000;

function emit(patch: Partial<OfflineSnapshot>) {
  snapshot = { ...snapshot, ...patch };
  listeners.forEach((listener) => listener());
}

function readOutbox(): PendingMutation[] {
  if (typeof window === "undefined") return [];
  try {
    const value = JSON.parse(window.localStorage.getItem(OUTBOX_KEY) ?? "[]");
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
}

function writeOutbox(items: PendingMutation[]) {
  window.localStorage.setItem(OUTBOX_KEY, JSON.stringify(items));
  emit({ pending: items.length });
}

export function initializeOfflineStore() {
  emit({ online: typeof navigator === "undefined" ? true : navigator.onLine, pending: readOutbox().length });
}

export function setNetworkOnline(online: boolean) {
  emit({ online });
  if (online) retryDelayMs = 1_000;
}

export function subscribeOfflineStore(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getOfflineSnapshot() {
  return snapshot;
}

export function getOfflineServerSnapshot(): OfflineSnapshot {
  return serverSnapshot;
}

export function queueMutation(input: Omit<PendingMutation, "id" | "createdAt" | "attempts">) {
  const items = readOutbox();
  const previous = items.find((item) => item.key === input.key);
  const next: PendingMutation = {
    ...input,
    id: previous?.id ?? crypto.randomUUID(),
    createdAt: previous?.createdAt ?? Date.now(),
    attempts: previous?.attempts ?? 0,
  };
  writeOutbox([...items.filter((item) => item.key !== input.key), next]);
  emit({ lastError: input.lastError ?? null });
  if (navigator.onLine) {
    if (flushTimer !== null) window.clearTimeout(flushTimer);
    flushTimer = window.setTimeout(() => void flushOutbox(), 1_500);
  }
  return next;
}

export function removeMutation(key: string) {
  writeOutbox(readOutbox().filter((item) => item.key !== key));
}

export async function flushOutbox(): Promise<void> {
  if (typeof window === "undefined" || !navigator.onLine || snapshot.flushing) return;
  emit({ flushing: true, lastError: null });
  try {
    for (const item of readOutbox()) {
      try {
        const response = await fetch(item.path, {
          method: item.method,
          credentials: "include",
          headers: { "Content-Type": "application/json", "X-Idempotency-Key": item.id },
          body: item.body,
          signal: AbortSignal.timeout(15_000),
        });
        if (!response.ok) {
          const raw = await response.text();
          let detail = raw;
          try {
            const parsed = JSON.parse(raw);
            if (typeof parsed?.detail === "string") detail = parsed.detail;
          } catch {
            // Keep plain-text response.
          }
          // Validation/auth/conflict errors need user intervention and must not loop forever.
          if (response.status < 500 && response.status !== 408 && response.status !== 429) {
            emit({ lastError: detail || `Speichern fehlgeschlagen (${response.status})` });
            break;
          }
          throw new Error(detail || `Backend nicht erreichbar (${response.status})`);
        }
        removeMutation(item.key);
        retryDelayMs = 1_000;
        window.dispatchEvent(new CustomEvent("hocx:mutation-flushed", { detail: { key: item.key } }));
      } catch (error) {
        const current = readOutbox();
        writeOutbox(current.map((entry) => entry.key === item.key ? {
          ...entry,
          attempts: entry.attempts + 1,
          lastError: error instanceof Error ? error.message : "Verbindungsfehler",
        } : entry));
        emit({ lastError: error instanceof Error ? error.message : "Verbindungsfehler" });
        if (navigator.onLine) {
          if (flushTimer !== null) window.clearTimeout(flushTimer);
          flushTimer = window.setTimeout(() => void flushOutbox(), retryDelayMs);
          retryDelayMs = Math.min(retryDelayMs * 2, 30_000);
        }
        break;
      }
    }
  } finally {
    emit({ flushing: false });
  }
}

export function saveDraft(key: string, value: string) {
  window.localStorage.setItem(`${DRAFT_PREFIX}${key}`, value);
}

export function readDraft(key: string): string | null {
  return typeof window === "undefined" ? null : window.localStorage.getItem(`${DRAFT_PREFIX}${key}`);
}

export function clearDraft(key: string) {
  window.localStorage.removeItem(`${DRAFT_PREFIX}${key}`);
}
