"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { PublicMaintenanceStatus } from "@/types/api";

// Während einer Wartung häufiger nachfragen, damit die Anmeldeseite das Ende schnell bemerkt;
// sonst selten (der Endpunkt ist billig, aber jede Seite des Logins pollt ihn).
const ACTIVE_POLL_MS = 15_000;
const IDLE_POLL_MS = 60_000;

export async function fetchMaintenanceStatus(): Promise<PublicMaintenanceStatus | null> {
  try {
    const response = await fetch("/api/public/maintenance-status", { cache: "no-store", credentials: "omit" });
    if (!response.ok) return null;
    return (await response.json()) as PublicMaintenanceStatus;
  } catch {
    return null;
  }
}

type MaintenanceStatusState = {
  status: PublicMaintenanceStatus | null;
  loaded: boolean;
  /** Zeitpunkt (ms) der nächsten automatischen Abfrage - für den Countdown der Wartungsseite. */
  nextCheckAt: number | null;
  /** Sofort neu abfragen (Button «Jetzt neu laden»); liefert den neuen Stand oder null. */
  refresh: () => Promise<PublicMaintenanceStatus | null>;
};

/** Öffentlicher Wartungsstatus mit Polling. `loaded` unterscheidet "noch nicht geladen" von "keine Wartung". */
export function useMaintenanceStatus(): MaintenanceStatusState {
  const [status, setStatus] = useState<PublicMaintenanceStatus | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [nextCheckAt, setNextCheckAt] = useState<number | null>(null);
  const statusRef = useRef<PublicMaintenanceStatus | null>(null);
  const loadRef = useRef<() => Promise<PublicMaintenanceStatus | null>>(async () => null);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function load(): Promise<PublicMaintenanceStatus | null> {
      if (timer) clearTimeout(timer);
      if (typeof document !== "undefined" && document.hidden && statusRef.current !== null) {
        schedule();
        return null;
      }
      const next = await fetchMaintenanceStatus();
      if (cancelled) return null;
      // Ein fehlgeschlagener Abruf ändert den letzten bekannten Stand nicht (keine falsche Entwarnung).
      if (next !== null) {
        statusRef.current = next;
        setStatus(next);
      }
      setLoaded(true);
      schedule();
      return next;
    }

    function schedule() {
      if (timer) clearTimeout(timer);
      const active = statusRef.current?.active || statusRef.current?.partial;
      const delay = active ? ACTIVE_POLL_MS : IDLE_POLL_MS;
      setNextCheckAt(Date.now() + delay);
      timer = setTimeout(() => void load(), delay);
    }

    function onVisible() {
      if (!document.hidden) {
        void load();
      }
    }

    loadRef.current = load;
    void load();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);

  const refresh = useCallback(() => loadRef.current(), []);
  return { status, loaded, nextCheckAt, refresh };
}

// --- Zustandswahl der Wartungsseite (1a Wartung / 1b Update) ------------------------------------

/** Ab hier gilt ein Update als «dauert länger» (gerechnet ab Beginn des Deploy-Fensters, sonst ab
 * Laden der Seite). Gleicher Wert in infra/maintenance/maintenance.html (SLOW_AFTER_MS). */
export const UPDATE_SLOW_AFTER_MS = 15 * 60 * 1000;

const VERSION_RE = /^[0-9A-Za-z][0-9A-Za-z._+-]{0,63}$/;

/** Öffentliche Versionskennung, sonst null (Anzeige nur geprüfter, kurzer Werte). */
export function cleanVersion(value: string | null | undefined): string | null {
  return value && VERSION_RE.test(value) ? value : null;
}

/** «1.5.0» → «v1.5.0»; Test-Images («test-…») ohne Präfix. */
export function versionLabel(version: string): string {
  return /^[0-9]/.test(version) ? `v${version}` : version;
}

export type MaintenanceEta =
  | { state: "known"; endAt: string; minutes: { low: number; high: number } | null; progress: { done: number; uncertainFrom: number } | null }
  | { state: "overdue" }
  | { state: "unknown" };

export type MaintenanceView =
  | { mode: "update"; slow: boolean; fromVersion: string | null; toVersion: string | null }
  | { mode: "maintenance"; eta: MaintenanceEta };

function timeOf(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const value = new Date(iso).getTime();
  return Number.isNaN(value) ? null : value;
}

/** Update-Seite nur für das Deploy-Fenster (kind "update"; ältere Backends: reason_code "deploy"),
 * sonst Wartung. Reine Funktion - getestet in maintenance.test.ts. */
export function maintenanceView(status: PublicMaintenanceStatus, now: number, pageLoadedAt: number): MaintenanceView {
  const isUpdate = status.kind ? status.kind === "update" : status.reason_code === "deploy";
  if (isUpdate) {
    const started = timeOf(status.started_at);
    const since = started !== null ? Math.min(started, pageLoadedAt) : pageLoadedAt;
    return {
      mode: "update",
      slow: now - since > UPDATE_SLOW_AFTER_MS,
      fromVersion: cleanVersion(status.from_version),
      toVersion: cleanVersion(status.to_version),
    };
  }
  if (status.estimate_state === "overdue") return { mode: "maintenance", eta: { state: "overdue" } };
  const end = timeOf(status.estimated_end_at);
  if (status.estimate_state !== "estimated" || end === null || !status.estimated_end_at) {
    return { mode: "maintenance", eta: { state: "unknown" } };
  }
  const minutes = remainingMinutes(status);
  const started = timeOf(status.started_at);
  let progress: { done: number; uncertainFrom: number } | null = null;
  if (started !== null && end > started) {
    const total = end - started;
    const clamp = (value: number) => Math.min(1, Math.max(0, value));
    const done = clamp((now - started) / total);
    const low = status.remaining_low_seconds !== null ? now + status.remaining_low_seconds * 1000 : end;
    progress = { done, uncertainFrom: Math.max(done, clamp((low - started) / total)) };
  }
  return { mode: "maintenance", eta: { state: "known", endAt: status.estimated_end_at, minutes, progress } };
}

/** Restzeit als Minutenspanne für die Anzeige - nie sekundengenau, nie ein Countdown auf null. */
export function remainingMinutes(status: PublicMaintenanceStatus): { low: number; high: number } | null {
  if (status.estimate_state !== "estimated" || status.remaining_high_seconds === null || status.remaining_low_seconds === null) {
    return null;
  }
  const high = Math.max(1, Math.ceil(status.remaining_high_seconds / 60));
  const low = Math.max(1, Math.min(high, Math.ceil(status.remaining_low_seconds / 60)));
  return { low, high };
}
