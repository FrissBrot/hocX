"use client";

import { useEffect, useRef, useState } from "react";

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

/** Öffentlicher Wartungsstatus mit Polling. `loaded` unterscheidet "noch nicht geladen" von "keine Wartung". */
export function useMaintenanceStatus(): { status: PublicMaintenanceStatus | null; loaded: boolean } {
  const [status, setStatus] = useState<PublicMaintenanceStatus | null>(null);
  const [loaded, setLoaded] = useState(false);
  const statusRef = useRef<PublicMaintenanceStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function load() {
      if (typeof document !== "undefined" && document.hidden && statusRef.current !== null) {
        schedule();
        return;
      }
      const next = await fetchMaintenanceStatus();
      if (cancelled) return;
      // Ein fehlgeschlagener Abruf ändert den letzten bekannten Stand nicht (keine falsche Entwarnung).
      if (next !== null) {
        statusRef.current = next;
        setStatus(next);
      }
      setLoaded(true);
      schedule();
    }

    function schedule() {
      const active = statusRef.current?.active || statusRef.current?.partial;
      timer = setTimeout(() => void load(), active ? ACTIVE_POLL_MS : IDLE_POLL_MS);
    }

    function onVisible() {
      if (!document.hidden) {
        if (timer) clearTimeout(timer);
        void load();
      }
    }

    void load();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);

  return { status, loaded };
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
