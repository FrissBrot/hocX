import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const fetchMock = vi.fn();
vi.mock("@/lib/api/client", () => ({ browserApiFetch: (...args: unknown[]) => fetchMock(...args), ApiError: class extends Error {} }));
const replace = vi.fn();
vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/security/audit",
  useRouter: () => ({ replace, push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(""),
}));

import { ToastProvider } from "@/contexts/toast-context";
import { AdminAuditLog } from "./admin-audit-log";

const entry = (id: number, action: string, outcome = "success", details = {}) => ({
  id, created_at: new Date(2026, 10, 21, 10, id).toISOString(), action, outcome, tenant_id: null, tenant_name: null,
  actor_email: "timo@example.com", actor_name: "Timo Weber", actor_kind: "user", actor_id: "00000000-0000-4000-8000-000000000001",
  ip_hash: "abcdef0123456789", entity_type: null, entity_id: null, details,
});
const page = { items: [entry(3, "user.login"), entry(2, "protocol.deleted", "failure", { field: "title", before: "A", after: "B" }), entry(1, "mystery.thing")], total: 3, retention_days: 730 };

describe("AdminAuditLog", () => {
  beforeEach(() => {
    // Die URL wird nur ersetzt, solange die Seite angezeigt wird (gleicher Pfad)
    window.history.pushState({}, "", "/admin/security/audit");
    replace.mockReset();
    fetchMock.mockReset();
    fetchMock.mockImplementation((path: string) => {
      if (path.startsWith("/api/admin/audit-log/timeline")) {
        return Promise.resolve({ range: "7d", bucket_seconds: 21600, buckets: [{ start: "2026-11-21T00:00:00Z", success: 2, failure: 1 }], totals: { events: 3, failures: 1, persons: 1, sources: 1 }, by_category: { user: 1, protocol: 1 }, retention_days: 730 });
      }
      if (path.startsWith("/api/admin/audit-log/views")) {
        return Promise.resolve({ range: "7d", counts: { all: 140, failures: 9, auth: 40, deletions: 6, admin: 3, privacy: 12 } });
      }
      if (path.startsWith("/api/admin/audit-log/filter-options")) return Promise.resolve({ entity_types: [], admins: [] });
      const match = /entries\/(\d+)/.exec(path);
      if (match) return Promise.resolve({ entry: page.items.find((item) => item.id === Number(match[1])), context: [] });
      return Promise.resolve(page);
    });
  });

  it("zeigt Fakten, Bereichs-Zähler, Tagesgruppe und unbekannte Aktionen als Code", async () => {
    render(<ToastProvider><AdminAuditLog initialPage={page} /></ToastProvider>);
    expect(screen.getByText(/Aufbewahrung 730 Tage/)).toBeInTheDocument();
    expect(screen.getByText("mystery.thing")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: /^Anmeldung\s*\d*$/ })).toHaveTextContent("1"));
    expect(screen.getByText("3 Ereignisse · 1 fehlgeschlagen")).toBeInTheDocument();
  });

  it("J öffnet den nächsten Eintrag in der Detail-Spalte, Vorher/Nachher nur mit Details", async () => {
    render(<ToastProvider><AdminAuditLog initialPage={page} /></ToastProvider>);
    await act(async () => {
      fireEvent.keyDown(document.body, { key: "j" });
    });
    await waitFor(() => expect(screen.getByRole("complementary")).toBeInTheDocument());
    expect(screen.queryByText("Änderung")).not.toBeInTheDocument();
    await act(async () => {
      fireEvent.keyDown(document.body, { key: "j" });
    });
    await waitFor(() => expect(screen.getByText("Änderung")).toBeInTheDocument());
    expect(replace).toHaveBeenLastCalledWith("/admin/security/audit?entry=2", { scroll: false });
  });

  it("gespeicherte Ansichten mit Zählern setzen Filter, Tokens werden zu Filtern (1.6)", async () => {
    render(<ToastProvider><AdminAuditLog initialPage={page} /></ToastProvider>);
    const deletions = await screen.findByRole("button", { name: /Löschungen/ });
    await waitFor(() => expect(deletions).toHaveTextContent("6"));
    expect(screen.getByRole("button", { name: /Alle Ereignisse/ })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(deletions);
    await waitFor(() => expect(deletions).toHaveAttribute("aria-pressed", "true"));
    await waitFor(() => expect(fetchMock.mock.calls.some(([path]) => String(path).startsWith("/api/admin/audit-log?") && String(path).includes("verb=deleted"))).toBe(true));

    const search = screen.getByRole("textbox", { name: "Suchen oder filtern" });
    fireEvent.change(search, { target: { value: "quelle:26ca vorgang:angesehen protocol" } });
    fireEvent.submit(search.closest("form") as HTMLFormElement);
    await waitFor(() => {
      const last = String(fetchMock.mock.calls.filter(([path]) => String(path).startsWith("/api/admin/audit-log?")).at(-1)?.[0]);
      expect(last).toContain("source=26ca");
      expect(last).toContain("verb=viewed");
      expect(last).toContain("action=protocol");
    });
    // «person:» setzt keinen Namen, sondern öffnet die Auswahl
    fireEvent.change(search, { target: { value: "person:Timo Weber" } });
    fireEvent.submit(search.closest("form") as HTMLFormElement);
    await waitFor(() => expect(replace.mock.calls.every(([url]) => !/timo|weber/i.test(String(url)))).toBe(true));
    expect(fetchMock.mock.calls.every(([path]) => !/timo|weber/i.test(String(path)))).toBe(true);
  });
});
