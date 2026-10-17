import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MaintenanceNotice } from "./maintenance-notice";
import { remainingMinutes } from "@/lib/maintenance";
import { PublicMaintenanceStatus } from "@/types/api";

function status(overrides: Partial<PublicMaintenanceStatus> = {}): PublicMaintenanceStatus {
  return {
    active: true,
    partial: false,
    block_scope: "all",
    reason_code: "manual",
    messages: {},
    affected_features: ["all"],
    started_at: "2026-10-14T12:00:00Z",
    estimate_state: "estimated",
    estimated_end_at: "2026-10-14T12:45:00Z",
    remaining_low_seconds: 20 * 60,
    remaining_high_seconds: 30 * 60,
    upcoming: [],
    updated_at: "2026-10-14T12:15:00Z",
    ...overrides,
  };
}

describe("MaintenanceNotice", () => {
  it("zeigt Titel, Standardtext und eine Minutenspanne statt Sekunden", () => {
    render(<MaintenanceNotice status={status()} />);
    expect(screen.getByText("hocX wird gerade gewartet")).toBeTruthy();
    expect(screen.getByText(/notwendige Wartungsarbeiten/)).toBeTruthy();
    expect(screen.getByText("Voraussichtlich noch 20–30 Minuten")).toBeTruthy();
    expect(screen.getByText(/Voraussichtlich wieder verfügbar/)).toBeTruthy();
    expect(screen.getByRole("status").getAttribute("aria-live")).toBe("polite");
  });

  it("bevorzugt die vom Admin hinterlegte Meldung", () => {
    render(<MaintenanceNotice status={status({ messages: { de: "Server-Umzug läuft" } })} />);
    expect(screen.getByText("Server-Umzug läuft")).toBeTruthy();
  });

  it("zeigt ohne seriöse Schätzung 'wird ermittelt'", () => {
    render(<MaintenanceNotice status={status({ estimate_state: "estimating", estimated_end_at: null, remaining_low_seconds: null, remaining_high_seconds: null })} />);
    expect(screen.getByText("Die voraussichtliche Dauer wird ermittelt.")).toBeTruthy();
  });

  it("zeigt bei Überschreitung einen klaren Hinweis statt eines Countdowns auf null", () => {
    render(<MaintenanceNotice status={status({ estimate_state: "overdue", remaining_low_seconds: null, remaining_high_seconds: null })} />);
    expect(screen.getByText(/dauern länger als erwartet/)).toBeTruthy();
    expect(screen.queryByText(/0 Minuten/)).toBeNull();
  });

  it("kündigt geplante Wartung an, ohne zu sperren", () => {
    render(<MaintenanceNotice status={status({ active: false, estimate_state: null, upcoming: [{ starts_at: "2026-10-20T18:00:00Z", ends_at: "2026-10-20T19:00:00Z", kind: "full", reason_code: "manual", messages: {} }] })} />);
    expect(screen.getByText("Geplante Wartung")).toBeTruthy();
    // Gleicher Tag: Wochentag/Datum einmal, dann Beginn – ca. Ende
    expect(screen.getByText(/^Dienstag, 20\. Oktober 2026 · \d\d:00 – ca\. \d\d:00$/)).toBeTruthy();
    expect(screen.getByText(/hocX ist von .* bis voraussichtlich .* nicht verfügbar/)).toBeTruthy();
  });

  it("zeigt bei angekündigter Wartung die Meldung des Admins", () => {
    render(<MaintenanceNotice status={status({ active: false, estimate_state: null, upcoming: [{ starts_at: "2026-10-24T20:00:00Z", ends_at: null, kind: "full", reason_code: "manual", messages: { de: "Update auf 1.2.0" } }] })} />);
    expect(screen.getByText("Update auf 1.2.0")).toBeTruthy();
    expect(screen.getByText(/· ab \d\d:00$/)).toBeTruthy();
  });

  it("zeigt nichts, wenn weder Wartung aktiv noch geplant ist", () => {
    const { container } = render(<MaintenanceNotice status={status({ active: false, estimate_state: null })} />);
    expect(container.textContent).toBe("");
  });
});

describe("remainingMinutes", () => {
  it("rundet auf ganze Minuten und fällt nie unter eine Minute", () => {
    expect(remainingMinutes(status({ remaining_low_seconds: 10, remaining_high_seconds: 30 }))).toEqual({ low: 1, high: 1 });
    expect(remainingMinutes(status({ remaining_low_seconds: 1201, remaining_high_seconds: 1800 }))).toEqual({ low: 21, high: 30 });
    expect(remainingMinutes(status({ estimate_state: "overdue" }))).toBeNull();
  });
});
