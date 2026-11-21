// Wartungsbanner der Abgabebox: Update (nur das Deploy-Fenster sperrt) oder Wartung - gleiche
// Regel wie frontend/lib/maintenance.ts (maintenanceView) und die statische Traefik-Seite.

export type BoxMaintenanceStatus = {
  active: boolean;
  uploads_blocked: boolean;
  kind?: "update" | "maintenance" | null;
  from_version?: string | null;
  to_version?: string | null;
  started_at?: string | null;
  estimated_end_at: string | null;
};

/** Ab hier «Das Update dauert länger» (wie UPDATE_SLOW_AFTER_MS im Hauptfrontend). */
export const UPDATE_SLOW_AFTER_MS = 15 * 60 * 1000;
const VERSION_RE = /^[0-9A-Za-z][0-9A-Za-z._+-]{0,63}$/;

export type BoxMaintenanceView =
  | { mode: "update"; slow: boolean; versions: string | null }
  | { mode: "maintenance" | "uploads" };

function label(version: string): string {
  return /^[0-9]/.test(version) ? `v${version}` : version;
}

export function boxMaintenanceView(status: BoxMaintenanceStatus, now: number, pageLoadedAt: number): BoxMaintenanceView | null {
  if (!status.active && !status.uploads_blocked) return null;
  if (!status.active) return { mode: "uploads" };
  if (status.kind !== "update") return { mode: "maintenance" };
  const started = status.started_at ? new Date(status.started_at).getTime() : Number.NaN;
  const since = Number.isNaN(started) ? pageLoadedAt : Math.min(started, pageLoadedAt);
  const from = status.from_version && VERSION_RE.test(status.from_version) ? status.from_version : null;
  const to = status.to_version && VERSION_RE.test(status.to_version) ? status.to_version : null;
  const versions = from && to && from !== to ? `${label(from)} → ${label(to)}` : to || from ? label((to || from) as string) : null;
  return { mode: "update", slow: now - since > UPDATE_SLOW_AFTER_MS, versions };
}
