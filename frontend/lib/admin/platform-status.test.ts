import { describe, expect, it } from "vitest";

import { derivePlatformStatus, percentDelta, problemHref } from "@/lib/admin/platform-status";
import type { OverviewSystemStatus } from "@/types/admin-overview";

function base(overrides: Partial<OverviewSystemStatus> = {}): OverviewSystemStatus {
  return {
    snapshot_at: "2026-11-21T10:00:00Z",
    stale: false,
    docker_unavailable: false,
    critical: 0,
    warning: 0,
    maintenance_active: false,
    maintenance_started_at: null,
    runtime_warning: false,
    overload_recent: 0,
    problems: [],
    ...overrides,
  };
}

describe("derivePlatformStatus (Plan §3.2)", () => {
  it("unknown ohne Snapshot, bei veraltetem Snapshot oder ohne Docker", () => {
    expect(derivePlatformStatus(null).status).toBe("unknown");
    expect(derivePlatformStatus(base({ snapshot_at: null })).status).toBe("unknown");
    expect(derivePlatformStatus(base({ stale: true, critical: 1 })).status).toBe("unknown");
    expect(derivePlatformStatus(base({ docker_unavailable: true })).rule).toBe("noData");
  });

  it("critical vor warning, mit den auslösenden Problemen", () => {
    const problems = [
      { key: "check:postgres", source: "check", subject: "postgres", reason: "down", severity: "critical" as const },
      { key: "job:x", source: "job", subject: "x", reason: "failing", severity: "warning" as const },
    ];
    const critical = derivePlatformStatus(base({ critical: 1, warning: 1, problems }));
    expect(critical.status).toBe("critical");
    expect(critical.problems.map((p) => p.key)).toEqual(["check:postgres"]);
    const warning = derivePlatformStatus(base({ warning: 1, problems: problems.slice(1) }));
    expect(warning.status).toBe("warning");
    expect(warning.problems).toHaveLength(1);
  });

  it("degraded bei Wartung, Laufzeit-Warnung oder Überlast ohne Probleme", () => {
    expect(derivePlatformStatus(base({ maintenance_active: true })).rule).toBe("maintenance");
    expect(derivePlatformStatus(base({ runtime_warning: true })).rule).toBe("runtime");
    expect(derivePlatformStatus(base({ overload_recent: 3 })).status).toBe("degraded");
    expect(derivePlatformStatus(base({ warning: 1, maintenance_active: true })).status).toBe("warning");
  });

  it("healthy ohne Befund", () => {
    expect(derivePlatformStatus(base())).toEqual({ status: "healthy", rule: "none", problems: [] });
  });
});

describe("problemHref / percentDelta", () => {
  it("verlinkt Jobs, Backups, Anmeldeschutz und Checks", () => {
    expect(problemHref({ key: "job:log_cleanup", source: "job", subject: "log_cleanup" })).toBe("/admin/jobs?job=log_cleanup");
    expect(problemHref({ key: "backup:x", source: "backup", subject: "x" })).toBe("/admin/backups");
    expect(problemHref({ key: "auth:spray", source: "auth", subject: "spray" })).toBe("/admin/security");
    expect(problemHref({ key: "check:redis", source: "check", subject: "redis" })).toBe("/admin/system?check=check%3Aredis");
  });

  it("liefert null ohne Vergleichsbasis", () => {
    expect(percentDelta(10, 0)).toBeNull();
    expect(percentDelta(10, null)).toBeNull();
    expect(percentDelta(12, 10)).toBe(20);
    expect(percentDelta(5, 10)).toBe(-50);
  });
});
