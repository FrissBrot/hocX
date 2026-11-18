import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();
const showToastMock = vi.fn();

vi.mock("@/lib/api/client", () => ({
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => showToastMock }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => vi.fn() }));

import { RoleManagement } from "./role-management";
import { PERMISSION_KEYS } from "@/lib/permissions.generated";

const ALL = [...PERMISSION_KEYS];

function renderEditor(actorPermissions: string[] = ALL) {
  return render(
    <RoleManagement initialRoles={[]} actorPermissions={actorPermissions} enabledFeatures={["finance", "abgabebox"]} canCustomize />,
  );
}

const checkbox = (label: string) => screen.getByRole("checkbox", { name: new RegExp(`^${label}`) }) as HTMLInputElement;

describe("RoleManagement – Rollen-Dialog (Phase 7)", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    showToastMock.mockReset();
  });

  it("hakt implizierte Rechte an, graut sie aus und nennt die Quelle", () => {
    renderEditor();
    fireEvent.click(screen.getByRole("button", { name: "Neue Rolle" }));
    fireEvent.click(checkbox("Sitzungen bearbeiten"));

    const drafts = checkbox("Entwürfe ansehen");
    expect(drafts.checked).toBe(true);
    expect(drafts.disabled).toBe(true);
    expect(drafts.closest("label")).toHaveClass("roles-permission-option-implied");
    expect(within(drafts.closest("label")!).getByText("Ergibt sich aus: Sitzungen bearbeiten")).toBeTruthy();
    // Das gewählte Recht selbst bleibt änderbar
    expect(checkbox("Sitzungen bearbeiten").disabled).toBe(false);
  });

  it("füllt das Formular aus einer Vorlage vor, inkl. Reichweite", () => {
    renderEditor();
    fireEvent.click(screen.getByRole("button", { name: "Aus Vorlage" }));
    fireEvent.click(screen.getByRole("button", { name: /^Abgabe-Prüfer/ }));

    expect((screen.getByRole("textbox", { name: "Name" }) as HTMLInputElement).value).toBe("Abgabe-Prüfer");
    expect(checkbox("Abgaben prüfen").checked).toBe(true);
    expect(checkbox("Abgaben ansehen").disabled).toBe(true);
    expect(checkbox("Abgaben verwalten").checked).toBe(false);
    const scopes = screen.getAllByRole("combobox", { name: "Reichweite" }) as HTMLSelectElement[];
    expect(scopes.map((select) => select.value)).toEqual(["assigned", "assigned"]);
    expect(screen.getByText(/Vorlage «Abgabe-Prüfer» übernommen/)).toBeTruthy();
  });

  it("schlägt aus Vorlagen nur eigene Rechte vor und nennt die weggelassenen", () => {
    renderEditor(["meetings.read", "meetings.read_drafts", "todos.complete_own", "participants.read", "finances.read", "access.manage"]);
    fireEvent.click(screen.getByRole("button", { name: "Aus Vorlage" }));
    const treasurer = screen.getByRole("button", { name: /^Kassier/ });
    expect(within(treasurer).getByText(/Berechtigungen hast du selbst nicht/)).toBeTruthy();
    fireEvent.click(treasurer);

    expect(checkbox("Kassenbuch ansehen").checked).toBe(true);
    const manage = checkbox("Finanzen verwalten");
    expect(manage.checked).toBe(false);
    expect(manage.disabled).toBe(true);
    expect(screen.getByText(/Nicht übernommen, weil du sie selbst nicht hast: .*Finanzen verwalten/)).toBeTruthy();
    // Speichern bleibt möglich (keine Rechteausweitung im Formular)
    expect(screen.getByRole("button", { name: "Speichern" })).not.toBeDisabled();
  });

  it("speichert eine Vorlage als normale eigene Rolle über POST /api/roles", async () => {
    browserApiFetchMock.mockResolvedValue({
      id: "r1", name: "Abgabe-Prüfer", system_key: null, description: null, permissions: [], scopes: {}, user_count: 0, locked: false,
    });
    renderEditor();
    fireEvent.click(screen.getByRole("button", { name: "Aus Vorlage" }));
    fireEvent.click(screen.getByRole("button", { name: /^Abgabe-Prüfer/ }));
    fireEvent.click(screen.getByRole("button", { name: "Speichern" }));

    await vi.waitFor(() => expect(browserApiFetchMock).toHaveBeenCalled());
    const [path, init] = browserApiFetchMock.mock.calls[0] as [string, { method: string; body: string }];
    expect(path).toBe("/api/roles");
    expect(init.method).toBe("POST");
    const body = JSON.parse(init.body);
    expect(body.name).toBe("Abgabe-Prüfer");
    expect([...body.permissions].sort()).toEqual(["meetings.read", "submissions.review", "todos.complete_own"]);
    expect(body.scopes).toEqual({ "submissions.read": "assigned", "submissions.review": "assigned" });
  });
});
