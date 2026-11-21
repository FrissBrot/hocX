import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();
vi.mock("@/lib/api/client", () => {
  class ApiError extends Error {
    constructor(message: string, public readonly kind: string, public readonly status?: number) {
      super(message);
    }
  }
  return { ApiError, browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args) };
});
vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/security",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  useSearchParams: () => new URLSearchParams("outcome=failure"),
}));

import { ApiError } from "@/lib/api/client";
import { SecurityAlertsView } from "./security-alerts";
import { SecurityEvents } from "./security-events";
import { SecurityOverview } from "./security-overview";
import { SecurityPolicyView } from "./security-policy";

function respond(map: Record<string, unknown>) {
  browserApiFetchMock.mockImplementation((path: unknown) => {
    if (typeof path !== "string") return Promise.resolve(undefined);
    const key = Object.keys(map).find((prefix) => path.startsWith(prefix));
    const value = key ? map[key] : undefined;
    return value instanceof Error ? Promise.reject(value) : Promise.resolve(value);
  });
}

describe("Sicherheitsbereich (Plattform)", () => {
  beforeEach(() => browserApiFetchMock.mockReset());

  it("Übersicht zeigt Kacheln und leere Zustände ohne Ereignisse", async () => {
    respond({
      "/api/admin/auth-security/overview": { failures_24h: 37, failures_prev_24h: 21, admin_logins_24h: 3, blocked_24h: 4, open_alerts: 1, critical_alerts: 0, active_blocks: 2 },
      "/api/admin/auth-security/summary": { timeseries: [], top_networks: [], top_accounts: [], active_blocks: [] },
      "/api/admin/auth-security/alerts": [{ key: "auth:account_attack:abc", rule: "account_attack", subject: "abc", severity: "warning", title: "x", message: "y" }],
    });
    render(<SecurityOverview />);
    expect(await screen.findByText("37")).toBeInTheDocument();
    expect(screen.getByText("Offene Warnungen")).toBeInTheDocument();
    expect(await screen.findByText("Konto unter Beschuss")).toBeInTheDocument();
    expect(screen.getByText("In den letzten 48 Stunden gab es keine Anmeldeereignisse.")).toBeInTheDocument();
    expect(screen.getByText("Keine Fehlversuche aus einzelnen Netzen.")).toBeInTheDocument();
  });

  it("support-Rolle (403) sieht einen Hinweis statt eines Fehlers", async () => {
    respond({ "/api/admin/auth-security": new ApiError("forbidden", "auth", 403) });
    render(<SecurityAlertsView />);
    expect(await screen.findByText("Diese Ansicht ist nur für Owner sichtbar.")).toBeInTheDocument();
  });

  it("Ereignisliste übernimmt den Filter aus der URL", async () => {
    respond({ "/api/admin/auth-security/events": [] });
    render(<SecurityEvents />);
    expect(await screen.findByText("Keine Ereignisse für diese Auswahl.")).toBeInTheDocument();
    expect(browserApiFetchMock.mock.calls[0][0]).toContain("outcome=failure");
  });

  it("Richtlinien zeigen Werte gruppiert", async () => {
    respond({ "/api/admin/auth-security/policy": { sessions: { auth_session_ttl_hours: 72 }, risk: { auth_risk_mode: "enforce" } } });
    render(<SecurityPolicyView />);
    expect(await screen.findByText("AUTH_SESSION_TTL_HOURS")).toBeInTheDocument();
    expect(screen.getByText("enforce")).toBeInTheDocument();
    expect(screen.getByText("Sitzungen")).toBeInTheDocument();
  });
});
