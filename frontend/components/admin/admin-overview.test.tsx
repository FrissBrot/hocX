import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();

vi.mock("@/lib/api/client", () => ({
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));
// recharts braucht im Test kein echtes Rendering
vi.mock("next/dynamic", () => ({ default: () => () => <div data-testid="chart" /> }));

import { AdminOverview } from "./admin-overview";
import type { AdminOverview as Overview } from "@/types/admin-overview";

function overview(overrides: Partial<Overview> = {}): Overview {
  return {
    generated_at: "2026-11-21T10:00:00Z",
    role: "owner",
    status: {
      snapshot_at: "2026-11-21T09:59:30Z",
      stale: false,
      docker_unavailable: false,
      critical: 0,
      warning: 1,
      maintenance_active: false,
      maintenance_started_at: null,
      runtime_warning: false,
      overload_recent: 0,
      problems: [{ key: "check:clamav_signatures", source: "check", subject: "clamav_signatures", reason: "stale", severity: "warning" }],
    },
    kpis: {
      tenants: { value: 42, new_30d: 3 },
      active_users_30d: { value: 318, previous: 300 },
      mrr: { value_rp: 123000, paying_tenants: 12, previous_month_income_rp: 118000, overdue_count: 1 },
      errors_24h: { value: 14, previous: 18 },
      login_failures_24h: { value: 37, previous: 21 },
    },
    todos: [{ key: "verifications", count: 2, href: "/admin/verifications", severity: "info", params: {} }],
    feed: [
      { id: "event:1", kind: "system", at: "2026-11-21T09:58:00Z", action: "problem", outcome: "stale", severity: "warning", tenant: null, actor: null, subject: "check:clamav_signatures", href: "/admin/system?check=check:clamav_signatures" },
    ],
    ...overrides,
  };
}

const series = { kind: "logins", range: "24h", bucket_hours: 1, points: [{ bucket: "2026-11-21T09:00:00Z", success: 3, failure: 1 }], top_types: [] };

describe("AdminOverview", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    browserApiFetchMock.mockImplementation((path: string) =>
      Promise.resolve(path.startsWith("/api/admin/overview/series") ? { ...series, kind: path.includes("errors") ? "errors" : "logins" } : overview()),
    );
  });

  it("zeigt Status mit auslösendem Problem, Kennzahlen, Aufgaben und Feed für owner", async () => {
    render(<AdminOverview initial={overview()} />);
    expect(screen.getByRole("heading", { name: "Plattform" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "check:clamav_signatures" })).toHaveAttribute("href", "/admin/system?check=check%3Aclamav_signatures");
    expect(screen.getByRole("link", { name: /Mandanten\s*42/ })).toHaveAttribute("href", "/admin/tenants");
    expect(screen.getByRole("link", { name: /2 Identitätsprüfungen offen/ })).toHaveAttribute("href", "/admin/verifications");
    expect(screen.getByText(/Problem: check:clamav_signatures/)).toBeInTheDocument();
    await waitFor(() => expect(browserApiFetchMock).toHaveBeenCalledWith("/api/admin/overview/series?kind=logins&range=24h"));
  });

  it("markiert owner-Felder für support als «Keine Berechtigung» und lädt keine Zeitreihen", () => {
    render(
      <AdminOverview
        initial={overview({ role: "support", status: null, feed: null, kpis: { ...overview().kpis, errors_24h: null, login_failures_24h: null } })}
      />,
    );
    expect(screen.getAllByText("Keine Berechtigung")).toHaveLength(3);
    expect(screen.queryByRole("heading", { name: "Plattform" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Aktivität" })).toBeNull();
    expect(browserApiFetchMock).not.toHaveBeenCalledWith(expect.stringContaining("/series"));
  });

  it("Zeitraum-Umschalter lädt die Zeitreihen neu, Feed-Filter blendet aus", async () => {
    render(<AdminOverview initial={overview()} />);
    fireEvent.click(screen.getByRole("tab", { name: "7 T" }));
    await waitFor(() => expect(browserApiFetchMock).toHaveBeenCalledWith("/api/admin/overview/series?kind=errors&range=7d"));
    fireEvent.click(screen.getByRole("tab", { name: "Admin" }));
    expect(screen.getByText("Keine Einträge.")).toBeInTheDocument();
  });

  it("zeigt einen Fehler, wenn die Übersicht fehlt", () => {
    render(<AdminOverview initial={null} />);
    expect(screen.getByText("Die Übersicht konnte nicht geladen werden.")).toBeInTheDocument();
  });
});
