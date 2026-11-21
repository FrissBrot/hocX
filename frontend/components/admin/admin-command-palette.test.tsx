import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { buildAdminNav } from "@/components/ui/admin-shell-nav";

const fetchMock = vi.fn();
vi.mock("@/lib/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/client")>();
  return { ...actual, browserApiFetch: (...args: unknown[]) => fetchMock(...args) };
});
const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }), usePathname: () => "/admin" }));

import { AdminCommandPalette } from "./admin-command-palette";

Element.prototype.scrollIntoView = vi.fn();

function renderPalette(role: "owner" | "support" = "owner", onAction = vi.fn()) {
  return render(<AdminCommandPalette open onClose={vi.fn()} navGroups={buildAdminNav(role)} adminId="a1" onAction={onAction} />);
}

describe("AdminCommandPalette", () => {
  afterEach(() => {
    fetchMock.mockReset();
    push.mockReset();
    window.localStorage.clear();
  });

  it("findet Seiten sofort und öffnet sie mit Enter", async () => {
    fetchMock.mockResolvedValue({ groups: [] });
    renderPalette();
    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "audit" } });
    expect(await screen.findByRole("option", { name: /Audit-Log/ })).toBeInTheDocument();
    fireEvent.keyDown(input, { key: "Enter" });
    expect(push).toHaveBeenCalledWith("/admin/security/audit");
    // Seiten landen in «Zuletzt geöffnet»
    expect(window.localStorage.getItem("hocx-admin-search-recent")).toContain("/admin/security/audit");
  });

  it("sucht Mandanten per POST ohne Begriff in der URL und merkt sie sich nicht", async () => {
    fetchMock.mockResolvedValue({ groups: [{ group: "tenants", items: [{ id: "t1", label: "Verein Alpha", sublabel: null, href: "/admin/tenants/t1" }] }] });
    renderPalette();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "alpha" } });
    const option = await screen.findByRole("option", { name: /Verein\s*Alpha/ });
    expect(fetchMock).toHaveBeenCalledWith("/api/admin/search", expect.objectContaining({ method: "POST", body: JSON.stringify({ q: "alpha" }) }));
    await act(async () => { fireEvent.click(option); });
    await waitFor(() => expect(push).toHaveBeenCalledWith("/admin/tenants/t1"));
    expect(window.localStorage.getItem("hocx-admin-search-recent")).toBeNull();
  });

  it("zeigt support keine owner-Seiten und führt Aktionen über den Aufrufer aus", async () => {
    fetchMock.mockResolvedValue({ groups: [] });
    const onAction = vi.fn();
    renderPalette("support", onAction);
    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "audit" } });
    await waitFor(() => expect(screen.queryByRole("option", { name: /Audit-Log/ })).toBeNull());
    fireEvent.change(input, { target: { value: "dunkel" } });
    const option = await screen.findByRole("option", { name: /dunkel/ });
    fireEvent.click(option);
    expect(onAction).toHaveBeenCalledWith("theme-dark");
  });
});
