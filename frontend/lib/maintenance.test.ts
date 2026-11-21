import { describe, expect, it } from "vitest";

import { UPDATE_SLOW_AFTER_MS, cleanVersion, maintenanceView, versionLabel } from "./maintenance";
import { cleanStatusPageUrl } from "./status-page-url";
import { PublicMaintenanceStatus } from "@/types/api";

const START = Date.parse("2026-11-21T12:00:00Z");

function status(overrides: Partial<PublicMaintenanceStatus> = {}): PublicMaintenanceStatus {
  return {
    active: true,
    partial: false,
    kind: "maintenance",
    from_version: null,
    to_version: null,
    block_scope: "all",
    reason_code: "manual",
    messages: {},
    affected_features: ["all"],
    started_at: "2026-11-21T12:00:00Z",
    estimate_state: "estimated",
    estimated_end_at: "2026-11-21T12:30:00Z",
    remaining_low_seconds: 10 * 60,
    remaining_high_seconds: 20 * 60,
    upcoming: [],
    updated_at: "2026-11-21T12:10:00Z",
    ...overrides,
  };
}

describe("maintenanceView – Zustandswahl", () => {
  it("Deploy-Fenster → Update-Seite mit Versionen", () => {
    const view = maintenanceView(status({ kind: "update", reason_code: "deploy", from_version: "1.5.0", to_version: "1.5.1" }), START + 60_000, START + 30_000);
    expect(view).toEqual({ mode: "update", slow: false, fromVersion: "1.5.0", toVersion: "1.5.1" });
  });

  it("älteres Backend ohne kind: reason_code deploy gilt als Update", () => {
    expect(maintenanceView(status({ kind: undefined, reason_code: "deploy" }), START, START).mode).toBe("update");
    expect(maintenanceView(status({ kind: undefined, reason_code: "manual" }), START, START).mode).toBe("maintenance");
  });

  it("kind maintenance gewinnt auch bei reason_code deploy (Admin-Wartung parallel zum Update)", () => {
    expect(maintenanceView(status({ kind: "maintenance", reason_code: "deploy" }), START, START).mode).toBe("maintenance");
  });

  it("Update «dauert länger» ab 15 Minuten seit Beginn des Deploy-Fensters", () => {
    const update = status({ kind: "update" });
    expect(maintenanceView(update, START + UPDATE_SLOW_AFTER_MS - 1000, START + 1000)).toMatchObject({ slow: false });
    expect(maintenanceView(update, START + UPDATE_SLOW_AFTER_MS + 1000, START + 1000)).toMatchObject({ slow: true });
  });

  it("ohne Beginn zählt das Laden der Seite", () => {
    const update = status({ kind: "update", started_at: null });
    const loaded = START + 5 * 60_000;
    expect(maintenanceView(update, loaded + UPDATE_SLOW_AFTER_MS - 1000, loaded)).toMatchObject({ slow: false });
    expect(maintenanceView(update, loaded + UPDATE_SLOW_AFTER_MS + 1000, loaded)).toMatchObject({ slow: true });
  });

  it("verwirft ungültige Versionen", () => {
    const view = maintenanceView(status({ kind: "update", from_version: "<img src=x>", to_version: "1.5.1" }), START, START);
    expect(view).toMatchObject({ fromVersion: null, toVersion: "1.5.1" });
  });

  it("Wartung mit ETA: Ende, Minutenspanne und Fortschritt mit Unsicherheitsbereich", () => {
    const view = maintenanceView(status(), START + 10 * 60_000, START);
    expect(view.mode).toBe("maintenance");
    if (view.mode !== "maintenance" || view.eta.state !== "known") throw new Error("ETA erwartet");
    expect(view.eta.endAt).toBe("2026-11-21T12:30:00Z");
    expect(view.eta.minutes).toEqual({ low: 10, high: 20 });
    expect(view.eta.progress?.done).toBeCloseTo(1 / 3);
    expect(view.eta.progress?.uncertainFrom).toBeCloseTo(2 / 3);
  });

  it("Wartung ohne ETA bzw. überzogen", () => {
    const unknown = maintenanceView(status({ estimate_state: "estimating", estimated_end_at: null, remaining_low_seconds: null, remaining_high_seconds: null }), START, START);
    expect(unknown).toEqual({ mode: "maintenance", eta: { state: "unknown" } });
    expect(maintenanceView(status({ estimate_state: "overdue" }), START, START)).toEqual({ mode: "maintenance", eta: { state: "overdue" } });
  });
});

describe("Versionen und Statusseite", () => {
  it("formatiert Versionen", () => {
    expect(versionLabel("1.5.1")).toBe("v1.5.1");
    expect(versionLabel("test-20261121-abc-r9")).toBe("test-20261121-abc-r9");
    expect(cleanVersion("1.5.1")).toBe("1.5.1");
    expect(cleanVersion("1.5 1")).toBeNull();
    expect(cleanVersion(null)).toBeNull();
  });

  it("lässt nur einfache https-Adressen als Statusseite zu", () => {
    expect(cleanStatusPageUrl("https://status.example.test/hocx")).toBe("https://status.example.test/hocx");
    expect(cleanStatusPageUrl("http://status.example.test")).toBeNull();
    expect(cleanStatusPageUrl("javascript:alert(1)")).toBeNull();
    expect(cleanStatusPageUrl("https://x.test/\"><script>")).toBeNull();
    expect(cleanStatusPageUrl("")).toBeNull();
  });
});
