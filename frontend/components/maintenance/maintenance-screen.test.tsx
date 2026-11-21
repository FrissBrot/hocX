import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MaintenanceScreen } from "./maintenance-screen";
import { maintenanceView, UPDATE_SLOW_AFTER_MS } from "@/lib/maintenance";
import { PublicMaintenanceStatus } from "@/types/api";

const START = Date.parse("2026-11-21T12:00:00Z");

function status(overrides: Partial<PublicMaintenanceStatus> = {}): PublicMaintenanceStatus {
  return {
    active: true,
    partial: false,
    kind: "maintenance",
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

function renderScreen(value: PublicMaintenanceStatus, now: number, extra: Partial<Parameters<typeof MaintenanceScreen>[0]> = {}) {
  return render(
    <MaintenanceScreen
      status={value}
      view={maintenanceView(value, now, now)}
      now={now}
      nextCheckAt={now + 12_000}
      runningVersion="1.5.0"
      statusPageUrl={null}
      onCheck={async () => {}}
      copyright={<span>©</span>}
      {...extra}
    />,
  );
}

describe("MaintenanceScreen – Wartung (1a)", () => {
  it("zeigt Titel, Standardtext, ETA mit Spanne, Fortschritt und Countdown", () => {
    renderScreen(status(), START + 10 * 60_000);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("hocX wird gerade gewartet");
    expect(screen.getByText("Wartung läuft")).toBeTruthy();
    expect(screen.getByText(/damit hocX stabil und sicher bleibt/)).toBeTruthy();
    expect(screen.getByText("Voraussichtlich wieder da")).toBeTruthy();
    expect(screen.getByText("Uhr")).toBeTruthy();
    expect(screen.getByText("noch 10–20 Min.")).toBeTruthy();
    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe("33");
    expect(screen.getByText("in 12 s")).toBeTruthy();
    expect(screen.getByText("v1.5.0")).toBeTruthy();
    expect(screen.getByRole("status").getAttribute("aria-live")).toBe("polite");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("ohne ETA: «Noch kein genauer Zeitpunkt», kein Balken", () => {
    renderScreen(status({ estimate_state: "estimating", estimated_end_at: null, remaining_low_seconds: null, remaining_high_seconds: null }), START);
    expect(screen.getByText("Noch kein genauer Zeitpunkt")).toBeTruthy();
    expect(screen.queryByRole("progressbar")).toBeNull();
  });

  it("bevorzugt die Meldung des Admins", () => {
    renderScreen(status({ messages: { de: "Server-Umzug läuft" } }), START);
    expect(screen.getByText("Server-Umzug läuft")).toBeTruthy();
  });
});

describe("MaintenanceScreen – Update (1b)", () => {
  const update = status({ kind: "update", reason_code: "deploy", from_version: "1.5.0", to_version: "1.5.1" });

  it("zeigt Update-Meldung, Versionen und neue Version unter der Karte", () => {
    renderScreen(update, START + 60_000);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("hocX wird aktualisiert");
    expect(screen.getByText("In wenigen Minuten ist hocX wieder da. Deine Daten sind sicher.")).toBeTruthy();
    expect(screen.getByText("Update von v1.5.0 auf v1.5.1")).toBeTruthy();
    expect(screen.getByText("v1.5.0 → v1.5.1").getAttribute("aria-hidden")).toBe("true");
    expect(screen.getByText("v1.5.1")).toBeTruthy();
    expect(screen.queryByText("Wartung läuft")).toBeNull();
    expect(screen.queryByText(/Statusseite/)).toBeNull();
  });

  it("ohne Versionen keine Versions-Pill", () => {
    renderScreen(status({ kind: "update" }), START);
    expect(screen.queryByText(/→/)).toBeNull();
  });

  it("«dauert länger» nach 15 Minuten, Statusseite nur wenn konfiguriert", () => {
    const late = START + UPDATE_SLOW_AFTER_MS + 60_000;
    const { unmount } = renderScreen(update, late);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Das Update dauert länger");
    expect(screen.queryByText(/Statusseite/)).toBeNull();
    unmount();
    renderScreen(update, late, { statusPageUrl: "https://status.example.test" });
    const link = screen.getByRole("link", { name: "der Statusseite" });
    expect(link.getAttribute("href")).toBe("https://status.example.test");
    expect(link.getAttribute("rel")).toContain("noopener");
  });

  it("«Jetzt neu laden» ist per Tastatur erreichbar und zeigt «Prüfe …» während der Prüfung", async () => {
    let resolve: () => void = () => {};
    const onCheck = vi.fn(() => new Promise<void>((done) => { resolve = done; }));
    renderScreen(update, START, { onCheck });
    const button = screen.getByRole("button", { name: "Jetzt neu laden" });
    expect(button.getAttribute("type")).toBe("button");
    button.focus();
    expect(document.activeElement).toBe(button);
    fireEvent.click(button);
    expect(onCheck).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Prüfe …" }).getAttribute("aria-busy")).toBe("true");
    await act(async () => { resolve(); });
    expect(screen.getByRole("button", { name: "Jetzt neu laden" })).toBeTruthy();
  });
});
