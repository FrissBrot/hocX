import { fireEvent, render as rtlRender, screen, within } from "@testing-library/react";
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
vi.mock("@/lib/admin-step-up", () => ({ stepUpFetch: (...args: unknown[]) => stepUpFetchMock(...args) }));
vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/security/blocks",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(""),
}));

import { ConfirmProvider } from "@/contexts/confirm-context";
import { ToastProvider } from "@/contexts/toast-context";
import { SecurityBlocks } from "./security-blocks";

function render(ui: ReactElement) {
  return rtlRender(
    <ToastProvider>
      <ConfirmProvider>{ui}</ConfirmProvider>
    </ToastProvider>,
  );
}

const now = Math.floor(Date.now() / 1000);
const BLOCK = {
  subject: "3f9a1c07be42aaaaaaaaaaaa", short: "3f9a1c07be42", scope: "net", until: now + 3600, reason: "source_hard", manual: false, stage: 4,
  remaining_seconds: 3600, created: now - 600, minutes: 70, admin_id: null, admin_name: null, incident_id: null, repeat: 2, rejected: 58,
};

function respond() {
  browserApiFetchMock.mockImplementation((path: string) => {
    if (path.startsWith("/api/admin/auth-security/blocks/ladder")) {
      return Promise.resolve({ events_24h: { observed: 41, limited: 6, challenged: 4 }, automatic: 1, manual: 0, strikes: 3, durations: [60, 360, 1440], max_automatic_minutes: 1440, max_manual_minutes: 43200 });
    }
    if (path.startsWith("/api/admin/auth-security/blocks/history")) {
      return Promise.resolve({
        start: new Date((now - 7 * 86400) * 1000).toISOString(), end: new Date(now * 1000).toISOString(),
        sources: [{ subject: "91cc02ae5f70", scope: "source", country: "DE", bars: [{ start: new Date((now - 86400) * 1000).toISOString(), end: new Date((now - 82800) * 1000).toISOString(), minutes: 60, manual: false, stage: 4, reason: "source_hard", cleared: false, replaced: false }] }],
      });
    }
    if (path.startsWith("/api/admin/auth-security/blocks")) return Promise.resolve([BLOCK]);
    return Promise.resolve(undefined);
  });
}

describe("Sperren-Seite (1.6)", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    stepUpFetchMock.mockReset();
    respond();
  });

  it("zeigt Abwehrleiter, Karte mit Grund, Abgewiesen-Zähler und Verlauf", async () => {
    render(<SecurityBlocks canWrite />);
    const card = await screen.findByRole("article", { name: "Sperre 3f9a1c07be42" });
    expect(within(card).getByText("58")).toBeInTheDocument();
    expect(within(card).getByText(/Harte Grenze der Quelle/)).toBeInTheDocument();
    expect(within(card).getAllByText("Automatisch").length).toBeGreaterThan(0);
    expect(screen.getByText("41")).toBeInTheDocument();
    expect(screen.getByText("Abwehrstufen")).toBeInTheDocument();
    // Tabellenalternative des Verlaufs
    fireEvent.click(screen.getByRole("button", { name: "Daten als Tabelle" }));
    expect(await screen.findByText("91cc02ae5f70")).toBeInTheDocument();
  });

  it("manuelle Sperre verlangt Adresse und Begründung, freie Minuten gehen mit", async () => {
    stepUpFetchMock.mockResolvedValue({ subject: "x", until: now + 60 });
    render(<SecurityBlocks canWrite />);
    fireEvent.click(await screen.findByRole("button", { name: "Manuelle Sperre" }));
    const dialog = await screen.findByRole("dialog");
    const save = within(dialog).getByRole("button", { name: "Mit Passkey sperren" });
    expect(save).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText(/^IP-Adresse/), { target: { value: "203.0.113.24" } });
    fireEvent.click(within(dialog).getByRole("tab", { name: "Eigene" }));
    fireEvent.change(within(dialog).getByLabelText(/^Dauer in Minuten/), { target: { value: "90" } });
    expect(save).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText(/^Grund/), { target: { value: "Abuse-Meldung #4471" } });
    expect(save).toBeEnabled();
    fireEvent.click(save);
    await vi.waitFor(() => expect(stepUpFetchMock).toHaveBeenCalled());
    const [purpose, path, init] = stepUpFetchMock.mock.calls[0];
    expect(purpose).toBe("security-block");
    expect(path).toBe("/api/admin/auth-security/blocks");
    expect(JSON.parse(init.body)).toEqual({ ip: "203.0.113.24", scope: "source", minutes: 90, reason: "Abuse-Meldung #4471" });
  });

  it("Verlängern schickt Minuten und Begründung mit Passkey", async () => {
    stepUpFetchMock.mockResolvedValue({ subject: BLOCK.subject, until: now + 7200 });
    render(<SecurityBlocks canWrite />);
    fireEvent.click(await screen.findByRole("button", { name: "Verlängern" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("tab", { name: "6 h" }));
    fireEvent.change(within(dialog).getByLabelText(/^Grund/), { target: { value: "Vorfall läuft" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Mit Passkey verlängern" }));
    await vi.waitFor(() => expect(stepUpFetchMock).toHaveBeenCalled());
    expect(stepUpFetchMock.mock.calls[0][1]).toBe(`/api/admin/auth-security/blocks/${BLOCK.subject}/extend`);
    expect(JSON.parse(stepUpFetchMock.mock.calls[0][2].body)).toEqual({ minutes: 360, reason: "Vorfall läuft" });
  });

  it("ohne Schreibrecht keine Aktionen", async () => {
    render(<SecurityBlocks canWrite={false} />);
    await screen.findByRole("article", { name: "Sperre 3f9a1c07be42" });
    expect(screen.queryByRole("button", { name: "Verlängern" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Manuelle Sperre" })).toBeNull();
  });
});
