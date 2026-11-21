import { describe, expect, it } from "vitest";

import { BoxMaintenanceStatus, UPDATE_SLOW_AFTER_MS, boxMaintenanceView } from "./maintenance-view";

const START = Date.parse("2026-11-21T12:00:00Z");
const base: BoxMaintenanceStatus = { active: true, uploads_blocked: true, kind: "maintenance", estimated_end_at: null };

describe("boxMaintenanceView", () => {
  it("ohne Sperre kein Banner", () => {
    expect(boxMaintenanceView({ ...base, active: false, uploads_blocked: false, kind: null }, START, START)).toBeNull();
  });

  it("Deploy → Update mit Versionen, sonst Wartung", () => {
    const update = { ...base, kind: "update" as const, from_version: "1.5.0", to_version: "1.5.1", started_at: "2026-11-21T12:00:00Z" };
    expect(boxMaintenanceView(update, START + 60_000, START)).toEqual({ mode: "update", slow: false, versions: "v1.5.0 → v1.5.1" });
    expect(boxMaintenanceView(base, START, START)).toEqual({ mode: "maintenance" });
    expect(boxMaintenanceView({ ...base, active: false }, START, START)).toEqual({ mode: "uploads" });
  });

  it("«dauert länger» nach 15 Minuten, ungültige Versionen weg", () => {
    const update = { ...base, kind: "update" as const, from_version: "<b>", to_version: "1.5.1", started_at: "2026-11-21T12:00:00Z" };
    expect(boxMaintenanceView(update, START + UPDATE_SLOW_AFTER_MS + 1, START + 1000)).toEqual({ mode: "update", slow: true, versions: "v1.5.1" });
  });
});
