import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();

vi.mock("@/lib/api/client", () => ({
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => vi.fn() }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => vi.fn(async () => true) }));

import { AdminMaintenance, formatClock } from "./admin-maintenance";
import { MaintenanceOverview, MaintenanceWindow } from "@/types/api";

function makeWindow(overrides: Partial<MaintenanceWindow> = {}): MaintenanceWindow {
  return {
    id: "w1",
    kind: "full",
    block_scope: "all",
    state: "active",
    reason_code: "manual",
    affected_features: ["all"],
    public_message: { de: "Update auf Version 1.2.0" },
    internal_note: null,
    source_job_type: null,
    source_job_id: null,
    scheduled_start_at: null,
    scheduled_end_at: null,
    started_at: new Date(Date.now() - 42 * 60_000).toISOString(),
    ended_at: null,
    estimate: null,
    estimated_end_at: new Date(Date.now() + 48 * 60_000).toISOString(),
    original_estimated_end_at: null,
    safety_margin_seconds: null,
    estimate_updated_at: null,
    progress: {},
    release_conditions: [],
    warnings: [],
    last_error: null,
    created_by_email: "admin@hocx.ch",
    created_at: new Date().toISOString(),
    conditions: [{ key: "no_open_storage_migration_cutover", satisfied: true, reason: "ok", params: {} }],
    ...overrides,
  } as MaintenanceWindow;
}

function overview(overrides: Partial<MaintenanceOverview> = {}): MaintenanceOverview {
  return { blocking: false, full_active: false, current: [], scheduled: [], history: [], history_total: 0, ...overrides };
}

describe("AdminMaintenance", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    browserApiFetchMock.mockResolvedValue(overview());
  });

  it("formatiert die Laufzeituhr", () => {
    expect(formatClock(42 * 60 + 18)).toBe("00:42:18");
    expect(formatClock(26 * 3600)).toBe("26:00:00");
  });

  it("zeigt eine laufende Wartung mit Uhr, Meldung und Sicherheitsprüfungen", () => {
    render(<AdminMaintenance initialOverview={overview({ blocking: true, full_active: true, current: [makeWindow()] })} />);

    expect(screen.getByText("Wartung läuft · Volle Wartung")).toBeInTheDocument();
    expect(screen.getByLabelText("Laufzeit")).toHaveTextContent(/^00:4[12]:\d\d$/);
    expect(screen.getByText("Update auf Version 1.2.0")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Sicherheitsprüfungen vor dem Beenden" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Wartung beenden" })).toBeEnabled();
  });

  it("sperrt das Beenden, solange eine Prüfung offen ist", () => {
    const window = makeWindow({ conditions: [{ key: "storage_not_fenced", satisfied: false, reason: "fenced", params: {} }] });
    render(<AdminMaintenance initialOverview={overview({ blocking: true, current: [window] })} />);

    expect(screen.getByText("Der Speicher ist noch schreibgesperrt")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Erst nach erfüllten Freigabebedingungen möglich" })).toBeDisabled();
  });

  it("zeigt geplante Wartungen als Karte und den Normalbetrieb mit nächstem Termin", () => {
    const start = new Date(Date.now() + 7 * 24 * 3600_000);
    const window = makeWindow({ state: "scheduled", started_at: null, estimated_end_at: null, scheduled_start_at: start.toISOString(), kind: "partial", block_scope: "writes" });
    render(<AdminMaintenance initialOverview={overview({ scheduled: [window] })} />);

    expect(screen.getByText("hocX ist normal erreichbar")).toBeInTheDocument();
    expect(screen.getByText(/Nächste Wartung in 7 Tagen/)).toBeInTheDocument();
    expect(screen.getByText("Schreibsperre")).toBeInTheDocument();
    expect(screen.getByText("«Update auf Version 1.2.0»")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Jetzt starten" })).toBeInTheDocument();
  });

  it("plant eine Schreibsperre über die Auswahlkarten", async () => {
    render(<AdminMaintenance initialOverview={overview()} />);
    expect(screen.getByText("Keine Wartung geplant.", { selector: ".maintenance-empty" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Wartung planen" }));
    fireEvent.click(screen.getByRole("radio", { name: /Schreibsperre/ }));
    expect(screen.getByText(/Bei einer Schreibsperre bleibt hocX lesbar/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Sofort kontrolliert starten" }));
    fireEvent.click(screen.getAllByRole("button", { name: "Jetzt starten" }).at(-1)!);

    await waitFor(() => expect(browserApiFetchMock).toHaveBeenCalledWith("/api/admin/maintenance", expect.objectContaining({ method: "POST" })));
    const body = JSON.parse(browserApiFetchMock.mock.calls.find((call) => call[1]?.method === "POST")![1].body);
    expect(body).toMatchObject({ kind: "partial", block_scope: "writes", start_now: true });
  });
});
