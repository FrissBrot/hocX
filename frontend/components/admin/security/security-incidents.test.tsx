import { fireEvent, render as rtlRender, screen, waitFor, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();
const stepUpFetchMock = vi.fn();
const replaceMock = vi.fn();
let search = "";
vi.mock("@/lib/api/client", () => {
  class ApiError extends Error {
    constructor(message: string, public readonly kind: string, public readonly status?: number) {
      super(message);
    }
  }
  return { ApiError, browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args) };
});
vi.mock("@/lib/admin-step-up", () => ({ stepUpFetch: (...args: unknown[]) => stepUpFetchMock(...args) }));
vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/security/incidents",
  useRouter: () => ({ replace: replaceMock, push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(search),
}));

import { ApiError } from "@/lib/api/client";
import { ConfirmProvider } from "@/contexts/confirm-context";
import { ToastProvider } from "@/contexts/toast-context";
import type { SecurityIncident, SecurityIncidentDetail, SecuritySituation } from "@/types/admin-security";

import { SecurityIncidents } from "./security-incidents";
import { SecuritySituationView } from "./security-situation";

function render(ui: ReactElement) {
  return rtlRender(
    <ToastProvider>
      <ConfirmProvider>{ui}</ConfirmProvider>
    </ToastProvider>,
  );
}

// Gekürztes Netz-Pseudonym der Testdaten (als Konstante: «key: <hex>» hält gitleaks sonst für einen Schlüssel)
const NET_SHORT = "3f9a1c07be42";

const incident: SecurityIncident = {
  id: 42, key: "auth:spraying:3f9a1c07be42", rule: "spraying", subject: "3f9a1c07be42", subject_label: null, severity: "critical",
  status: "new", active: true, trigger_count: 1, first_seen_at: "2026-11-26T09:12:00Z", last_triggered_at: "2026-11-26T09:50:00Z",
  cleared_at: null, acknowledged_at: null, closed_at: null, updated_at: "2026-11-26T09:12:00Z", assignee: null, tenant: null,
  window_minutes: 15, spark: [0, 1, 2, 4, 8, 12, 9, 3, 1, 0, 0, 0],
};

const detail: SecurityIncidentDetail = {
  ...incident,
  window: { start: "2026-11-26T08:57:00Z", end: "2026-11-26T10:00:00Z" },
  facts: { events: 420, failures: 412, blocked: 6, challenged: 2, successes: 0, accounts: 14, networks: 1, tenants: 3, countries: 1 },
  max_risk: 62, stage: 4,
  participants: { networks: [{ key: NET_SHORT, events: 420, failures: 412, country: "NL" }], accounts: [], tenants: [], countries: [{ code: "NL", events: 420, failures: 412 }] },
  reasons: [{ code: "new_device", count: 12, weight: 10 }],
  timeline: [
    { kind: "activity", id: 1, at: "2026-11-26T09:12:00Z", type: "triggered", admin: null, from: null, to: "critical", note: null },
    { kind: "event", at: "2026-11-26T09:13:00Z", event_id: "e1", event_type: "login.password", outcome: "failure", risk_score: 35, subject: "7c2e91a0f3b1", net: "3f9a1c07be42", country: "NL", marker: "first", stage: null, block_scope: null },
  ],
  notes: [], assignees: [{ id: "me-id", name: "Remo" }], can_block: true, event_filter: { net: "3f9a1c07be42" }, me: "me-id",
};

function respond(map: Record<string, unknown>) {
  browserApiFetchMock.mockImplementation((path: unknown) => {
    if (typeof path !== "string") return Promise.resolve(undefined);
    const key = Object.keys(map).sort((a, b) => b.length - a.length).find((prefix) => path.startsWith(prefix));
    const value = key ? map[key] : undefined;
    return value instanceof Error ? Promise.reject(value) : Promise.resolve(value);
  });
}

const STATS = { open: 1, critical: 1, unassigned: 1, new: 1, mtta_seconds: 1740, mttr_seconds: null, false_positives: 2, closed: 9, false_positive_rate: 2 / 9, days: 30 };

describe("Vorfälle (1.6)", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    stepUpFetchMock.mockReset();
    replaceMock.mockReset();
    search = "";
  });

  it("zeigt Kennzahlen, Liste und öffnet den Vorfall per Tastatur, Nummer in der URL", async () => {
    respond({
      "/api/admin/auth-security/incidents/stats": STATS,
      "/api/admin/auth-security/incidents/42": detail,
      "/api/admin/auth-security/incidents?": { items: [incident], total: 1, offset: 0, limit: 50, counts: { open: 1, new: 1, in_progress: 0, closed: 0, all: 1 } },
    });
    render(<SecurityIncidents />);
    expect(await screen.findByText("29 min")).toBeInTheDocument();
    expect(screen.getByText("22 %")).toBeInTheDocument();
    const open = await screen.findByRole("button", { name: "INC-0042 öffnen" });
    expect(screen.getByText("Netz 3f9a1c07be42")).toBeInTheDocument();
    open.focus();
    fireEvent.click(open);
    const drawer = await screen.findByRole("complementary", { name: "Password Spraying aus einem Netz" });
    expect(within(drawer).getAllByText("412").length).toBeGreaterThan(0);
    expect(within(drawer).getByText("Erstes Ereignis: login.password · Fehlschlag")).toBeInTheDocument();
    await waitFor(() => expect(replaceMock).toHaveBeenLastCalledWith("/admin/security/incidents?incident=42", { scroll: false }));
    fireEvent.keyDown(drawer, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("complementary")).toBeNull());
  });

  it("Übernehmen, Abschliessen mit Begründung und Notiz laufen über den Passkey", async () => {
    search = "incident=42";
    stepUpFetchMock.mockResolvedValue({});
    respond({
      "/api/admin/auth-security/incidents/stats": STATS,
      "/api/admin/auth-security/incidents/42": detail,
      "/api/admin/auth-security/incidents?": { items: [incident], total: 1, offset: 0, limit: 50, counts: { open: 1, new: 1, in_progress: 0, closed: 0, all: 1 } },
    });
    render(<SecurityIncidents />);
    fireEvent.click(await screen.findByRole("button", { name: "Übernehmen" }));
    await waitFor(() => expect(stepUpFetchMock).toHaveBeenCalledWith("security-incident", "/api/admin/auth-security/incidents/42/assign", { method: "POST", body: JSON.stringify({ admin_id: "me-id" }) }));

    fireEvent.click(screen.getByRole("button", { name: /^Neu/ }));
    fireEvent.click(await screen.findByRole("menuitemradio", { name: /Fehlalarm/ }));
    const dialog = await screen.findByRole("dialog", { name: "Status «Fehlalarm» setzen" });
    fireEvent.change(within(dialog).getByLabelText(/^Begründung \(optional\)/), { target: { value: "Vereinsabend" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Mit Passkey bestätigen" }));
    await waitFor(() => expect(stepUpFetchMock).toHaveBeenCalledWith("security-incident", "/api/admin/auth-security/incidents/42/status", {
      method: "POST", body: JSON.stringify({ status: "false_positive", note: "Vereinsabend" }),
    }));

    fireEvent.change(screen.getByLabelText(/^Notiz hinzufügen/), { target: { value: "Hosting-Netz" } });
    fireEvent.click(screen.getByRole("button", { name: "Notiz mit Passkey speichern" }));
    await waitFor(() => expect(stepUpFetchMock).toHaveBeenCalledWith("security-incident", "/api/admin/auth-security/incidents/42/notes", {
      method: "POST", body: JSON.stringify({ note: "Hosting-Netz" }),
    }));
  });

  it("support-Rolle (403) sieht einen Hinweis", async () => {
    respond({ "/api/admin/auth-security": new ApiError("forbidden", "auth", 403) });
    render(<SecurityIncidents />);
    expect(await screen.findByText("Diese Ansicht ist nur für Owner sichtbar.")).toBeInTheDocument();
  });
});

describe("Lagebild (1.6)", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    search = "";
  });

  const points = Array.from({ length: 48 }, (_, index) => ({
    start: new Date(Date.UTC(2026, 10, 25, 10) + index * 1800_000).toISOString(), failures: index === 47 ? 412 : 1, blocked: 0, challenged: 0, successes: 3,
  }));
  const situation: SecuritySituation = {
    range: "24h", start: points[0].start, end: "2026-11-26T10:00:00Z", bucket_minutes: 30,
    posture: { level: "attack", attack_mode: false, open: 1, critical: 1, active_rules: 1, rules_near: 0 },
    points,
    totals: { failures: 459, blocked: 0, challenged: 0, successes: 144, admin_logins: 2 },
    previous: { failures: 31, blocked: 0, challenged: 0, successes: 140, admin_logins: 2 },
    incident_stats: STATS,
    markers: [{ id: 42, rule: "spraying", severity: "critical", status: "new", at: "2026-11-26T09:12:00Z" }],
    heatmap: [{ dow: 3, hour: 9, count: 412 }], heatmap_days: 7,
    countries: [{ code: "NL", failures: 412 }, { code: null, failures: 3 }],
    networks: [{ net: "3f9a1c07be42", failures: 412, accounts: 14, tenants: 3, country: "NL" }],
    accounts: [{ subject: "7c2e91a0f3b1", failures: 61, networks: 1 }],
    active_blocks: 2,
  };

  it("zeigt Lage, Kennzahlen, Markierungen und Tabellenalternativen", async () => {
    respond({
      "/api/admin/auth-security/situation": situation,
      "/api/admin/auth-security/incidents/42": detail,
      "/api/admin/auth-security/incidents?": { items: [incident], total: 1, offset: 0, limit: 8, counts: { open: 1, new: 1, in_progress: 0, closed: 0, all: 1 } },
      "/api/admin/auth-security/alert-rules": [],
    });
    render(<SecuritySituationView />);
    expect(await screen.findByText("1 kritischer Vorfall offen, die Regel löst noch aus. Die Abwehr greift automatisch.")).toBeInTheDocument();
    expect(screen.getByText("1381 % ggü. Vorperiode (31)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^#42 öffnen, erkannt/ })).toBeInTheDocument();
    // ohne Auswahl: der offene Vorfall im Detail
    expect(await screen.findByRole("complementary", { name: "Password Spraying aus einem Netz" })).toBeInTheDocument();
    const heatmap = screen.getByRole("img", { name: "Fehlversuche nach Wochentag und Stunde" });
    expect(heatmap).toHaveAttribute("aria-describedby");
    const toggles = screen.getAllByRole("button", { name: "Daten als Tabelle" });
    fireEvent.click(toggles[1]);
    expect(await screen.findByRole("rowheader", { name: "Mi" })).toBeInTheDocument();
    expect(screen.getByText("Niederlande (NL)")).toBeInTheDocument();
    expect(screen.getByText("unbekannt")).toBeInTheDocument();
    // Live umschalten
    const live = screen.getByRole("button", { name: "Live" });
    fireEvent.click(live);
    expect(screen.getByRole("button", { name: "Pausiert" })).toHaveAttribute("aria-pressed", "false");
  });
});
