import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SYSTEM_ROLE_PERMISSIONS } from "@/lib/permissions.generated";
import type { SessionInfo } from "@/types/api";

const fetchMock = vi.fn();
vi.mock("@/lib/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/client")>();
  return { ...actual, browserApiFetch: (...args: unknown[]) => fetchMock(...args) };
});
const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }), usePathname: () => "/" }));

import { GlobalSearch } from "./global-search";

// jsdom kennt scrollIntoView nicht (die Suche scrollt den aktiven Treffer ins Bild)
Element.prototype.scrollIntoView = vi.fn();

const session = {
  authenticated: true,
  user: { id: "u1", display_name: "A B" },
  current_tenant: { id: "t1", name: "Verein", enabled_features: ["finance", "abgabebox", "todo_fines"] },
  permissions: [...SYSTEM_ROLE_PERMISSIONS.admin],
  roles: [{ id: "r-admin", name: null, system_key: "admin" }],
} as unknown as SessionInfo;

function renderSearch() {
  return render(<GlobalSearch open onClose={vi.fn()} session={session} listInput={null} onAction={vi.fn()} />);
}

describe("GlobalSearch", () => {
  afterEach(() => {
    fetchMock.mockReset();
    push.mockReset();
  });

  it("zeigt Einstellungen, Rollen, Elemente und Blöcke und öffnet Blöcke im Editor", async () => {
    fetchMock.mockImplementation((url: string) => {
      if (url === "/api/roles") return Promise.resolve([{ id: "r1", name: null, system_key: "kassier", description: null, permissions: [], user_count: 1, locked: false }]);
      return Promise.resolve({
        people: [], files: [],
        elements: [{ id: "e1", title: "Ämtliplan", description: null }],
        blocks: [{ element_id: "e1", element_title: "Ämtliplan", block_id: 2, title: "Küchenämtli" }],
      });
    });
    renderSearch();
    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "dsgvo" } });
    expect(await screen.findByRole("option", { name: /Datenschutz-Statistik/ })).toBeInTheDocument();

    fireEvent.change(input, { target: { value: "kassier" } });
    expect(await screen.findByRole("option", { name: /Kassier/ })).toBeInTheDocument();

    fireEvent.change(input, { target: { value: "kuche" } });
    const block = await screen.findByRole("option", { name: /Küchenämtli/ });
    expect(screen.getByRole("option", { name: /^Ämtliplan$/ })).toBeInTheDocument();
    await act(async () => { fireEvent.click(block); });
    await waitFor(() => expect(push).toHaveBeenCalledWith("/elements?open=e1&block=2"));
  });

  it("zeigt Listen als eigene Gruppe mit Hervorhebung, öffnet sie und merkt sie nicht", async () => {
    window.localStorage.clear();
    fetchMock.mockImplementation((url: string, init?: { body?: string }) => {
      if (url === "/api/roles") return Promise.resolve([]);
      // Suchbegriff im Body, nicht in der Adresse
      expect(url).toBe("/api/search");
      expect(JSON.parse(init?.body ?? "{}")).toEqual({ q: "getranke" });
      return Promise.resolve({
        people: [], files: [], elements: [], blocks: [],
        lists: [{ id: "l1", name: "Getränkeliste", description: "Wer bringt was" }],
      });
    });
    renderSearch();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "getranke" } });
    const option = await screen.findByRole("option", { name: /Getränkeliste/ });
    expect(screen.getAllByRole("option")[0]).toBe(option);
    expect(screen.getByText("Listen")).toHaveClass("global-search-group");
    expect(option.querySelector("mark.global-search-hit")?.textContent).toBe("Getränke");
    await act(async () => { fireEvent.keyDown(screen.getByRole("combobox"), { key: "Enter" }); });
    await waitFor(() => expect(push).toHaveBeenCalledWith("/lists?open=l1"));
    expect(window.localStorage.getItem("hocx-search-recent")).toBeNull();
  });

  it("fragt ohne meetings.edit keine Listen ab", async () => {
    const reader = { ...session, permissions: ["meetings.read"], roles: [] } as unknown as SessionInfo;
    render(<GlobalSearch open onClose={vi.fn()} session={reader} listInput={null} onAction={vi.fn()} />);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "amtli" } });
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(fetchMock).not.toHaveBeenCalledWith("/api/search", expect.anything());
  });
});
