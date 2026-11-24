import { fireEvent, render as rtlRender, screen, waitFor, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();
const stepUpFetchMock = vi.fn();
vi.mock("@/lib/api/client", () => {
  class ApiError extends Error {
    constructor(message: string, public readonly kind: string, public readonly status?: number) {
      super(message);
    }
  }
  return { ApiError, browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args) };
});
vi.mock("@/lib/admin-step-up", () => ({ stepUpFetch: (...args: unknown[]) => stepUpFetchMock(...args), stepUpDownload: vi.fn() }));
vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/security/events",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(""),
}));

import { ConfirmProvider } from "@/contexts/confirm-context";
import { ToastProvider } from "@/contexts/toast-context";
import { SecurityEvents } from "./security-events";

function render(ui: ReactElement) {
  return rtlRender(
    <ToastProvider>
      <ConfirmProvider>{ui}</ConfirmProvider>
    </ToastProvider>,
  );
}

const EVENT_ID = "0193a6f0-0000-7000-8000-000000000001";
const ROW = {
  event_id: EVENT_ID, ts: "2026-11-23T09:24:00Z", event_type: "login.password", outcome: "failure", actor_kind: "anonymous", platform_admin_id: null,
  tenant_id: null, tenant_name: "Turnverein", subject_hash: "7c2e91a0f3b1", src_net_hash: "3f9a1c07be42", device_hash: null, src_country: "NL",
  risk_score: 70, risk_reasons: ["spraying", "new_device"], enforcement: "none", user_agent_family: "Chrome · Windows",
};
const DETAIL = {
  ...ROW, policy_version: "risk-v1", endpoint: "/api/auth/login", host_kind: "main", details: {}, related: { net: 22, subject: 4, country: 30 },
  related_hours: 24, can_block: true, has_weights: true, reasons: [{ code: "spraying", weight: 25 }, { code: "new_device", weight: 10 }],
};
const HISTOGRAM = {
  start: "2026-11-22T10:00:00Z", end: "2026-11-23T10:00:00Z", bucket_seconds: 1800, total: 1,
  buckets: [{ start: "2026-11-23T09:00:00Z", success: 0, failure: 1, blocked: 0, challenged: 0, info: 0 }],
  outcome_counts: { success: 0, failure: 1, blocked: 0, challenged: 0, info: 0 },
};

function respond() {
  browserApiFetchMock.mockImplementation((path: string) => {
    if (path.startsWith("/api/admin/auth-security/events/histogram")) return Promise.resolve(HISTOGRAM);
    if (path.startsWith(`/api/admin/auth-security/events/${EVENT_ID}`)) return Promise.resolve(DETAIL);
    if (path.startsWith("/api/admin/auth-security/events?")) return Promise.resolve({ items: [ROW], next_cursor: "abc", start: HISTOGRAM.start, end: HISTOGRAM.end });
    return Promise.resolve(undefined);
  });
}

function listCalls(): string[] {
  return browserApiFetchMock.mock.calls.map(([path]) => String(path)).filter((path) => path.startsWith("/api/admin/auth-security/events?"));
}

describe("Ereignisse (1.6)", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    stepUpFetchMock.mockReset();
    respond();
  });

  it("Klick auf ein Netz-Pseudonym filtert danach, Token-Eingabe ebenso", async () => {
    render(<SecurityEvents />);
    fireEvent.click(await screen.findByRole("button", { name: "Nach netz 3f9a1c07be42 filtern" }));
    await waitFor(() => expect(listCalls().at(-1)).toContain("net=3f9a1c07be42"));
    const input = screen.getByLabelText("Filter eingeben");
    fireEvent.change(input, { target: { value: "land:nl" } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);
    await waitFor(() => expect(listCalls().at(-1)).toContain("country=NL"));
    fireEvent.change(input, { target: { value: "person:timo" } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);
    expect(await screen.findByText(/Unbekannter Filter/)).toBeInTheDocument();
  });

  it("Ältere lädt mit Cursor (Keyset), Neuere geht zurück", async () => {
    render(<SecurityEvents />);
    fireEvent.click(await screen.findByRole("button", { name: "Ältere" }));
    await waitFor(() => expect(listCalls().at(-1)).toContain("cursor=abc"));
    fireEvent.click(screen.getByRole("button", { name: "Neuere" }));
    await waitFor(() => expect(listCalls().at(-1)).not.toContain("cursor="));
  });

  it("Detail zeigt Gewichte und sperrt die Quelle mit Passkey", async () => {
    stepUpFetchMock.mockResolvedValue({ subject: "x", until: 1 });
    render(<SecurityEvents />);
    fireEvent.click(await screen.findByRole("button", { name: /Ereignis login.password von/ }));
    const drawer = await screen.findByRole("complementary");
    expect(await within(drawer).findByText("+25")).toBeInTheDocument();
    expect(within(drawer).getByText("Risiko 70 · hoch")).toBeInTheDocument();
    fireEvent.click(within(drawer).getByRole("button", { name: "Quelle sperren" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText(/^Grund/), { target: { value: "Spraying aus NL" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Mit Passkey sperren" }));
    await waitFor(() => expect(stepUpFetchMock).toHaveBeenCalled());
    expect(stepUpFetchMock.mock.calls[0][0]).toBe("security-block");
    expect(stepUpFetchMock.mock.calls[0][1]).toBe(`/api/admin/auth-security/events/${EVENT_ID}/block`);
    expect(JSON.parse(stepUpFetchMock.mock.calls[0][2].body)).toEqual({ minutes: 60, reason: "Spraying aus NL" });
  });
});
