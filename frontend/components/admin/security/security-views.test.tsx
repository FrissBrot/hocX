import { fireEvent, render as rtlRender, screen, waitFor, within } from "@testing-library/react";
import type { ReactElement } from "react";
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
import { ConfirmProvider } from "@/contexts/confirm-context";
import { ToastProvider } from "@/contexts/toast-context";

// Warnungen (Quittieren) und Ereignisse (Konto anzeigen) brauchen Rückfrage und Toast
function render(ui: ReactElement) {
  return rtlRender(
    <ToastProvider>
      <ConfirmProvider>{ui}</ConfirmProvider>
    </ToastProvider>,
  );
}
import { SecurityAlertRules } from "./security-alert-rules";
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
    respond({
      "/api/admin/auth-security/events/histogram": { start: "2026-11-22T10:00:00Z", end: "2026-11-23T10:00:00Z", bucket_seconds: 1800, buckets: [], outcome_counts: { success: 0, failure: 0, blocked: 0, challenged: 0, info: 0 }, total: 0 },
      "/api/admin/auth-security/events": { items: [], next_cursor: null, start: "2026-11-22T10:00:00Z", end: "2026-11-23T10:00:00Z" },
    });
    render(<SecurityEvents />);
    expect(await screen.findByText("Keine Ereignisse für diese Auswahl.")).toBeInTheDocument();
    const listCall = browserApiFetchMock.mock.calls.find(([path]) => String(path).startsWith("/api/admin/auth-security/events?"));
    expect(listCall?.[0]).toContain("outcome=failure");
    expect(listCall?.[0]).toContain("range=24h");
  });

  it("Warnungen lassen sich nach Rückfrage quittieren (1.5.1)", async () => {
    respond({
      "/api/admin/auth-security/alerts": [{ key: "auth:spraying:abc", rule: "spraying", subject: "abc", severity: "warning", title: "x", message: "y", acknowledged_at: null }],
      "/api/admin/auth-security/alerts/ack": { key: "auth:spraying:abc", acknowledged: true },
    });
    render(<SecurityAlertsView />);
    fireEvent.click(await screen.findByRole("button", { name: "Quittieren" }));
    const dialog = await screen.findByRole("dialog", { name: "Warnung quittieren" });
    fireEvent.change(within(dialog).getByLabelText(/^Notiz \(optional\)/), { target: { value: "wird geprüft" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Quittieren" }));
    await waitFor(() =>
      expect(browserApiFetchMock).toHaveBeenCalledWith(
        "/api/admin/auth-security/alerts/ack",
        expect.objectContaining({ method: "POST", body: JSON.stringify({ key: "auth:spraying:abc", note: "wird geprüft" }) }),
      ),
    );
  });

  it("Alarmregeln zeigen Messwert gegen Schwelle und die Kurve der gewählten Regel (1.6)", async () => {
    const rule = (name: string, state: string, value: number) => ({
      rule: name, window_minutes: 15, value, threshold: 10, comparator: ">=", state, severity: "warning", fired: state === "fired" ? 1 : 0,
      triggers_30d: 2, daily_30d: Array(30).fill(0), recent: [{ at: "2026-11-22T09:24:00Z", subject: "3f9a1c07be42", severity: "warning" }],
      settings: { auth_alert_spraying_accounts: 10 },
    });
    respond({
      "/api/admin/auth-security/alert-rules/spraying/series": { rule: "spraying", bucket_minutes: 15, hours: 24, threshold: 10, comparator: ">=", points: [{ start: "2026-11-23T09:00:00Z", value: 14 }] },
      "/api/admin/auth-security/alert-rules": [rule("spraying", "fired", 14), rule("tenant", "quiet", 1)],
    });
    render(<SecurityAlertRules />);
    expect(await screen.findByRole("heading", { name: "Password Spraying aus einem Netz", level: 2 })).toBeInTheDocument();
    expect(screen.getByText("14 / 10 Konten · Warnung · 15 min")).toBeInTheDocument();
    expect(screen.getByText("AUTH_ALERT_SPRAYING_ACCOUNTS")).toBeInTheDocument();
    expect(await screen.findByText(/Höchster Wert 14, Schwelle 10; 1 Abschnitt über der Schwelle/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /Ruhig/ }));
    expect(await screen.findByRole("button", { name: /Viele Konten eines Mandanten/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Password Spraying/ })).toBeNull();
  });

  it("Richtlinien zeigen Werte gruppiert", async () => {
    respond({ "/api/admin/auth-security/policy": { sessions: { auth_session_ttl_hours: 72 }, risk: { auth_risk_mode: "enforce" } } });
    render(<SecurityPolicyView />);
    expect(await screen.findByText("AUTH_SESSION_TTL_HOURS")).toBeInTheDocument();
    expect(screen.getByText("enforce")).toBeInTheDocument();
    expect(screen.getByText("Sitzungen")).toBeInTheDocument();
  });
});
