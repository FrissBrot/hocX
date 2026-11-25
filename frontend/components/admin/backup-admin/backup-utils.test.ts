import { describe, expect, it } from "vitest";

import type { BackupJob } from "@/types/api";

import { buildTimeline, levelDue, retentionEstimate, runHoursOfDay, savingsPercent, scheduleSlotsForDay, zurichDay } from "./backup-utils";

function job(overrides: Partial<BackupJob>): BackupJob {
  return {
    id: "j", kind: "backup", trigger: "schedule", state: "completed", requested_by_email: null, created_at: "2026-11-24T12:16:00Z", started_at: null,
    finished_at: null, heartbeat_at: null, worker_active: false, attempt: 0, cancel_requested: false, progress: {}, error_code: null, error_message: null,
    warning_count: 0, duration_seconds: 17, backup_set: null, ...overrides,
  };
}

describe("Zeitplan in Schweizer Zeit (UTC-Versatz bleibt, Frage 1 a)", () => {
  it("zeigt im Winter 01:15, 07:15, 13:15, 19:15", () => {
    expect(runHoursOfDay("2026-11-24", 6, 15)).toEqual([1.25, 7.25, 13.25, 19.25]);
  });

  it("verschiebt die Läufe im Sommer um eine Stunde", () => {
    expect(runHoursOfDay("2026-07-01", 6, 15)).toEqual([2.25, 8.25, 14.25, 20.25]);
  });

  it("ordnet Läufe dem Schweizer Kalendertag zu", () => {
    const slots = scheduleSlotsForDay("2026-11-24", 6, 15);
    expect(slots).toHaveLength(4);
    expect(slots.every((at) => zurichDay(at) === "2026-11-24")).toBe(true);
    expect(new Date(slots[0]).toISOString()).toBe("2026-11-24T00:15:00.000Z");
  });
});

describe("7-Tage-Raster", () => {
  const settings = { interval_hours: 6, schedule_offset_minutes: 15, schedule_enabled: true };
  const now = Date.parse("2026-11-24T16:00:00Z");

  it("zeigt Ergebnis, verpasste und geplante Läufe", () => {
    const days = buildTimeline([
      job({ id: "a", created_at: "2026-11-24T00:15:30Z", state: "completed" }),
      job({ id: "b", created_at: "2026-11-24T06:16:00Z", state: "partial" }),
      job({ id: "v", kind: "verify", trigger: "manual", created_at: "2026-11-24T10:00:00Z" }),
    ], settings, now);
    expect(days).toHaveLength(7);
    const today = days[6];
    expect(today.day).toBe("2026-11-24");
    expect(today.slots.map((slot) => slot.state)).toEqual(["ok", "partial", "missed", "planned"]);
    expect(today.worst).toBe("missed");
    expect(today.marks).toEqual([expect.objectContaining({ kind: "verify" })]);
  });

  it("fasst bei mehr als 8 Läufen pro Tag zusammen (Frage 5 a)", () => {
    const days = buildTimeline([], { ...settings, interval_hours: 1 }, now);
    expect(days[0].summary).toBe(true);
    expect(buildTimeline([], { ...settings, interval_hours: 3 }, now)[0].summary).toBe(false);
  });

  it("hat ohne Zeitplan keine Slots", () => {
    expect(buildTimeline([], { ...settings, schedule_enabled: false }, now).every((day) => day.slots.length === 0)).toBe(true);
  });
});

describe("Nachweise und Speicher", () => {
  it("rechnet den verstrichenen Anteil des Intervalls", () => {
    const now = Date.parse("2026-11-24T12:00:00Z");
    expect(levelDue("2026-11-24T09:00:00Z", 6 * 3_600_000, now)).toMatchObject({ pct: 50, overdue: false });
    expect(levelDue("2026-11-23T00:00:00Z", 6 * 3_600_000, now)).toMatchObject({ pct: 100, overdue: true });
    expect(levelDue(null, 1000, now)).toMatchObject({ overdue: true, dueAt: null });
  });

  it("zeigt die echte Ersparnis über alle Punkte statt einer Fantasiezahl", () => {
    expect(savingsPercent(300 * 1024 ** 3, 7.6 * 1024 ** 3)).toBe(97);
    expect(savingsPercent(null, 10)).toBeNull();
  });

  it("schätzt Rückblick und Punkte der Aufbewahrung", () => {
    const estimate = retentionEstimate({ interval_hours: 6, keep_within_days: 14, keep_daily: 14, keep_weekly: 8, keep_monthly: 12 });
    expect(estimate.lookbackDays).toBe(360);
    expect(estimate.points).toBeGreaterThan(56);
    expect(estimate.segments.map((segment) => segment.key)).toEqual(["within", "weekly", "monthly"]);
  });
});
