"use client";

import { clientMessage } from "@/lib/i18n/client-messages";

export type PendingMutation = {
  id: string;
  key: string;
  path: string;
  method: "PUT" | "PATCH";
  body: string;
  createdAt: number;
  attempts: number;
  lastError?: string;
  // Set when the backend rejected this mutation with a non-retryable (4xx, non-408/429)
  // response - most notably a 409 conflict. Retrying it unchanged would just keep losing
  // in the exact same way, so flushOutbox skips it on every future flush until
  // either a fresh edit re-queues the same key (queueMutation always starts a new item
  // without this flag) or the user explicitly discards it (discardMutation/
  // discardBlockedMutations) via the "verwerfen" action surfaced in ConnectivityStatus.
  blocked?: boolean;
};

export type OfflineSnapshot = {
  online: boolean;
  pending: number;
  flushing: boolean;
  lastError: string | null;
  blocked: number;
};

const OUTBOX_KEY = "hocx-offline-outbox-v1";
const DRAFT_PREFIX = "hocx-draft-v1:";
let snapshot: OfflineSnapshot = { online: true, pending: 0, flushing: false, lastError: null, blocked: 0 };
const serverSnapshot: OfflineSnapshot = { online: true, pending: 0, flushing: false, lastError: null, blocked: 0 };
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
  emit({ pending: items.length, blocked: items.filter((item) => item.blocked).length });
}

export function initializeOfflineStore() {
  const items = readOutbox();
  emit({
    online: typeof navigator === "undefined" ? true : navigator.onLine,
    pending: items.length,
    blocked: items.filter((item) => item.blocked).length,
  });
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
  // Jeder neue Body bekommt eine eigene id: flushOutbox entfernt nach Erfolg nur den Eintrag
  // mit genau der gesendeten id. Mit der alten id loeschte ein waehrend des Sendens
  // eingereihter, neuerer Body sich selbst mit (Audit MAIN-FE-011).
  const next: PendingMutation = {
    ...input,
    id: crypto.randomUUID(),
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

// Entfernt den Eintrag nur, wenn er noch genau die gesendete Fassung ist. Gibt false zurueck,
// wenn inzwischen ein neuerer Body fuer denselben Key eingereiht wurde.
function removeSentMutation(item: PendingMutation): boolean {
  const items = readOutbox();
  const current = items.find((entry) => entry.key === item.key);
  if (current && current.id !== item.id) return false;
  writeOutbox(items.filter((entry) => entry.key !== item.key));
  return true;
}

// Explicit user-facing "verwerfen" action for a mutation that keeps failing with a
// non-retryable error (see the `blocked` flag on PendingMutation / flushOutbox below).
// Unlike removeMutation (used after a successful send), this fires a
// "hocx:mutation-discarded" event so callers that keyed local UI state to a mutation
// (e.g. the protocol editor's per-block save indicator) can react instead of the item
// just silently vanishing from the outbox.
export function discardMutation(key: string) {
  const items = readOutbox();
  if (!items.some((item) => item.key === key)) return;
  writeOutbox(items.filter((item) => item.key !== key));
  window.dispatchEvent(new CustomEvent("hocx:mutation-discarded", { detail: { key } }));
}

// Bulk variant surfaced from ConnectivityStatus: discards every mutation currently
// blocked on a non-retryable error, leaving unrelated still-retryable mutations queued.
export function discardBlockedMutations() {
  const items = readOutbox();
  const blocked = items.filter((item) => item.blocked);
  if (blocked.length === 0) return;
  writeOutbox(items.filter((item) => !item.blocked));
  for (const item of blocked) {
    window.dispatchEvent(new CustomEvent("hocx:mutation-discarded", { detail: { key: item.key } }));
  }
  emit({ lastError: null });
}

export async function flushOutbox(): Promise<void> {
  if (typeof window === "undefined" || !navigator.onLine || snapshot.flushing) return;
  emit({ flushing: true, lastError: null });
  let replacedDuringFlush = false;
  try {
    for (const item of readOutbox()) {
      // Blockierte Eintraege (nicht wiederholbare 4xx) erst nach neuer Eingabe oder Verwerfen
      // wieder senden - unveraendert wuerden sie bei jedem Flush erneut abgelehnt.
      if (item.blocked) continue;
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
          // Validation/auth/conflict errors need user intervention and must not loop forever -
          // but they also must not stop every *other*, unrelated queued mutation behind this
          // one from ever being attempted (a plain `break` here used to exit the whole loop,
          // and since this item is never removed from the outbox except on success, every
          // future flush hit the exact same item first and stalled identically forever). Mark
          // just this item as blocked and move on to the rest of the outbox; it stays queued
          // (visible via ConnectivityStatus's "verwerfen" action) until the user discards it or
          // a fresh edit re-queues the same key.
          if (response.status < 500 && response.status !== 408 && response.status !== 429) {
            const message = detail || clientMessage("saveFailedStatus", { status: response.status });
            const current = readOutbox();
            writeOutbox(current.map((entry) => entry.id === item.id ? {
              ...entry,
              attempts: entry.attempts + 1,
              lastError: message,
              blocked: true,
            } : entry));
            emit({ lastError: message });
            continue;
          }
          throw new Error(detail || clientMessage("unreachableStatus", { status: response.status }));
        }
        retryDelayMs = 1_000;
        if (removeSentMutation(item)) {
          window.dispatchEvent(new CustomEvent("hocx:mutation-flushed", { detail: { key: item.key } }));
        } else {
          replacedDuringFlush = true;
        }
      } catch (error) {
        const current = readOutbox();
        writeOutbox(current.map((entry) => entry.id === item.id ? {
          ...entry,
          attempts: entry.attempts + 1,
          lastError: error instanceof Error ? error.message : clientMessage("connectionError"),
        } : entry));
        emit({ lastError: error instanceof Error ? error.message : clientMessage("connectionError") });
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
  // Ein waehrend dieses Laufs neu eingereihter Body: queueMutations eigener Flush-Timer lief
  // ins Leere, solange dieser Lauf noch aktiv war - also direkt nachsenden.
  if (replacedDuringFlush && navigator.onLine) {
    if (flushTimer !== null) window.clearTimeout(flushTimer);
    flushTimer = window.setTimeout(() => void flushOutbox(), 0);
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
