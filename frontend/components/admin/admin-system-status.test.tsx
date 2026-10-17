import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();

vi.mock("@/lib/api/client", () => ({
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));

import { AdminSystemStatus } from "./admin-system-status";
import { ContainerStatusEntry, SystemStatus } from "@/types/api";

function makeContainer(overrides: Partial<ContainerStatusEntry> = {}): ContainerStatusEntry {
  return {
    name: "hocx-backend-1",
    service: "backend",
    container_id: "abc123def456",
    state: "running",
    health: "healthy",
    health_output: null,
    restart_count: 0,
    started_at: "2026-10-09T12:00:00Z",
    exit_code: null,
    oom_killed: false,
    image: "ghcr.io/acme/hocx-backend:1.2.0",
    version: "1.2.0",
    cpu_percent: 1.5,
    memory_bytes: 512 * 1024 * 1024,
    memory_limit_bytes: 1024 * 1024 * 1024,
    status: "ok",
    reasons: [],
    ...overrides,
  };
}

function makeStatus(overrides: Partial<SystemStatus> = {}): SystemStatus {
  return {
    snapshot: {
      collected_at: "2026-10-11T12:00:00Z",
      docker_configured: true,
      docker_available: true,
      docker_error: null,
      compose_project: "hocx",
      containers: [makeContainer()],
      checks: [
        { key: "storage", status: "warning", params: { freePercent: 9.9, freeGb: 7.8, totalGb: 78.6 }, error: null },
        { key: "clamav", status: "critical", params: {}, error: "ConnectionError: refused" },
      ],
    },
    stale: false,
    problems: [],
    events: [],
    ...overrides,
  };
}

describe("AdminSystemStatus", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
  });

  it("zeigt Dienste, Container und den Gesamtzustand", () => {
    render(<AdminSystemStatus initialStatus={makeStatus()} />);

    expect(screen.getByRole("heading", { name: "Alles in Ordnung" })).toBeInTheDocument();
    expect(screen.getByText("Keine offenen Probleme.")).toBeInTheDocument();
    // Dienste fachlich gruppiert, je Gruppe mit Anteil OK
    expect(screen.getByRole("heading", { name: "Infrastruktur" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Sicherheit" })).toBeInTheDocument();
    expect(screen.getAllByText("0/1 OK")).toHaveLength(2);
    expect(screen.getByText("Speicherplatz")).toBeInTheDocument();
    expect(screen.getByText("9,9 % frei · 7,8 von 78,6 GB")).toBeInTheDocument();
    expect(screen.getByText("Nicht erreichbar: ConnectionError: refused")).toBeInTheDocument();
    expect(screen.getByText("backend")).toBeInTheDocument();
    expect(screen.getByText("2 Tage")).toBeInTheDocument();
    expect(screen.getByText("1.2.0")).toBeInTheDocument();
    expect(screen.getByText(/^512.*MB von 1.*GB$/)).toBeInTheDocument();
  });

  it("blendet mit «Nur Auffälligkeiten» Dienste im Zustand OK aus", () => {
    const status = makeStatus();
    status.snapshot!.checks.push({ key: "redis", status: "ok", params: { latencyMs: 1, usedMb: 1.3 }, error: null });
    render(<AdminSystemStatus initialStatus={status} />);

    expect(screen.getByText("Redis")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Nur Auffälligkeiten" }));
    expect(screen.queryByText("Redis")).not.toBeInTheDocument();
    expect(screen.getByText("Speicherplatz")).toBeInTheDocument();
  });

  it("übersetzt Probleme und Ereignisse anhand ihrer Schlüssel", () => {
    render(
      <AdminSystemStatus
        initialStatus={makeStatus({
          problems: [
            { key: "container:backend", source: "container", subject: "backend", reason: "unhealthy", severity: "critical", title: "x", message: "y", first_seen_at: null },
            { key: "check:storage", source: "check", subject: "storage", reason: "warning", severity: "warning", title: "x", message: "y", first_seen_at: null },
          ],
          events: [
            { id: 2, kind: "resolved", subject: "job:export_cleanup", reason: "failing", severity: "info", title: "x", message: "y", created_at: "2026-10-11T11:00:00Z" },
            { id: 1, kind: "container_restart", subject: "container:frontend", reason: "restarted", severity: "warning", title: "x", message: "y", created_at: "2026-10-11T10:00:00Z" },
          ],
        })}
      />,
    );

    expect(screen.getByRole("heading", { name: "1 kritisches Problem, 1 Warnung" })).toBeInTheDocument();
    expect(screen.getByText("Container backend ist unhealthy")).toBeInTheDocument();
    expect(screen.getByText("Speicherplatz knapp")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Storage →" })).toHaveAttribute("href", "/admin/storage");
    // Ereignisse: Art als eigene Markierung, der Text ohne «Behoben:»-Präfix
    const resolved = screen.getByText("Job export_cleanup ist fehlgeschlagen").closest("li")!;
    expect(within(resolved).getByText("Behoben")).toBeInTheDocument();
    expect(screen.getByText("Container frontend wurde neu gestartet")).toBeInTheDocument();
  });

  it("warnt bei veraltetem Stand und fehlender Container-Übersicht", () => {
    const status = makeStatus({ stale: true });
    status.snapshot = { ...status.snapshot!, docker_configured: false, containers: [] };
    render(<AdminSystemStatus initialStatus={status} />);

    expect(screen.getByText(/Der Systemstatus ist veraltet/)).toBeInTheDocument();
    expect(screen.getByText(/Die Container-Übersicht ist nicht eingerichtet/)).toBeInTheDocument();
  });
});
