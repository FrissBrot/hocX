import type { OverviewProblem, OverviewSystemStatus } from "@/types/admin-overview";

export type PlatformStatus = "healthy" | "degraded" | "warning" | "critical" | "unknown";

export type PlatformStatusResult = {
  status: PlatformStatus;
  /** Auslösende Regel (Übersetzungsschlüssel adminOverview.status.rules.<rule>) */
  rule: "noData" | "critical" | "warning" | "maintenance" | "runtime" | "overload" | "none";
  /** Auslösende Probleme (nur bei critical/warning), schwerste zuerst */
  problems: OverviewProblem[];
};

/**
 * Plattformstatus nach Plan §3.2 - reine Funktion, damit Dashboard, Glocke und Tests dieselbe Regel nutzen.
 * Reihenfolge: Unknown (kein/veralteter Snapshot, Docker nicht erreichbar) → Critical → Warning →
 * Degraded (Wartung, Laufzeit-Warnung, Überlast in den letzten 5 min) → Healthy.
 */
export function derivePlatformStatus(input: OverviewSystemStatus | null): PlatformStatusResult {
  if (!input || input.snapshot_at === null || input.stale || input.docker_unavailable) {
    return { status: "unknown", rule: "noData", problems: input?.problems ?? [] };
  }
  if (input.critical > 0) {
    return { status: "critical", rule: "critical", problems: input.problems.filter((p) => p.severity === "critical") };
  }
  if (input.warning > 0) {
    return { status: "warning", rule: "warning", problems: input.problems.filter((p) => p.severity === "warning") };
  }
  if (input.maintenance_active) return { status: "degraded", rule: "maintenance", problems: [] };
  if (input.runtime_warning) return { status: "degraded", rule: "runtime", problems: [] };
  if (input.overload_recent > 0) return { status: "degraded", rule: "overload", problems: [] };
  return { status: "healthy", rule: "none", problems: [] };
}

/** Deep Link zu einem Problemschlüssel (`<quelle>:<subjekt>`), wie im Aktivitätsfeed. */
export function problemHref(problem: Pick<OverviewProblem, "key" | "source" | "subject">): string {
  if (problem.source === "job") return `/admin/jobs?job=${encodeURIComponent(problem.subject)}`;
  if (problem.source === "backup") return "/admin/backups";
  if (problem.source === "auth") return "/admin/security";
  return `/admin/system?check=${encodeURIComponent(problem.key)}`;
}

/** Relative Veränderung in Prozent (gerundet), null ohne Vergleichsbasis. */
export function percentDelta(current: number, previous: number | null | undefined): number | null {
  if (previous === null || previous === undefined || previous === 0) return null;
  return Math.round(((current - previous) / previous) * 100);
}
