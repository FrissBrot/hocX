import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();
vi.mock("@/lib/api/client", () => ({ browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args) }));
const confirmMock = vi.fn();
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => confirmMock }));
const toastMock = vi.fn();
vi.mock("@/contexts/toast-context", () => ({ useToast: () => toastMock }));

import { SecurityActivity } from "./security-activity";
import type { TenantSecurityActivity } from "@/types/admin-security";

const DATA: TenantSecurityActivity = {
  summary: { failures_24h: 12, accounts_with_failures_24h: 1, new_device_logins_7d: 1, blocked_24h: 0 },
  warnings: [{ kind: "account_attack", user_id: "u-1", display_name: "Anna Muster", count: 12, last_at: "2026-11-20T10:00:00Z" }],
  accounts: [{ user_id: "u-1", display_name: "Anna Muster", last_login: null, failures_7d: 12, active_sessions: 2 }],
  events: [{ ts: "2026-11-20T10:00:00Z", event_type: "mfa.remove", outcome: "success", user_id: "u-1", display_name: "Anna Muster", user_agent_family: "Firefox", risk_level: "high" }],
};

describe("SecurityActivity (Mandant)", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    confirmMock.mockReset();
    toastMock.mockReset();
  });

  it("zeigt Warnungen, Konten und Ereignisse ohne Netzdaten", () => {
    render(<SecurityActivity initial={DATA} canRevoke={false} />);
    expect(screen.getByText("Anna Muster: 12 Fehlversuche in 24 Stunden")).toBeInTheDocument();
    expect(screen.getByText("Noch nie")).toBeInTheDocument();
    expect(screen.getByText("Zweiter Faktor entfernt")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sitzungen beenden" })).not.toBeInTheDocument();
  });

  it("leere Daten zeigen die Leerzustände", () => {
    render(<SecurityActivity initial={{ ...DATA, warnings: [], accounts: [], events: [] }} canRevoke />);
    expect(screen.getByText("Keine Warnungen in den letzten 7 Tagen.")).toBeInTheDocument();
    expect(screen.getByText("Keine Ereignisse in den letzten 7 Tagen.")).toBeInTheDocument();
  });

  it("beendet Sitzungen nach Bestätigung (access.manage)", async () => {
    confirmMock.mockResolvedValue(true);
    browserApiFetchMock.mockResolvedValueOnce({ revoked: 2 }).mockResolvedValueOnce({ ...DATA, accounts: [{ ...DATA.accounts[0], active_sessions: 0 }] });
    render(<SecurityActivity initial={DATA} canRevoke />);
    fireEvent.click(screen.getByRole("button", { name: "Sitzungen beenden" }));
    await waitFor(() => expect(toastMock).toHaveBeenCalledWith("2 Sitzungen beendet.", "success"));
    expect(browserApiFetchMock.mock.calls[0][0]).toBe("/api/auth-security/accounts/u-1/revoke-sessions");
    expect(browserApiFetchMock.mock.calls[0][1]).toMatchObject({ method: "POST" });
  });
});
