// «Mitglied erfassen» mit Einladung: Die Person wird zuerst angelegt, danach Rolle/Einladung.
// Scheiterte ein Folgeschritt (z. B. Benutzerlimit erreicht), blieb der Dialog offen mit
// «Speichern fehlgeschlagen» - die Person existierte aber schon, fehlte in der Liste, und ein
// zweiter Klick auf «Erfassen» legte sie doppelt an.
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/client";
import type { ParticipantSummary, RoleRead } from "@/types/api";

const api = vi.hoisted(() => vi.fn());
const toast = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/client")>()),
  browserApiFetch: (url: string, init?: unknown) => api(url, init),
}));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => toast }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => vi.fn().mockResolvedValue(true) }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }) }));

import { ParticipantManager } from "./participant-manager";

const created = {
  id: "p-new", display_name: "Neu Mitglied", first_name: "Neu", last_name: "Mitglied", email: "neu@example.org",
  is_active: true, joined_at: null, left_at: null, login_enabled: false, login_status: "none", roles: [],
} as unknown as ParticipantSummary;
const existing = { ...created, id: "p-old", display_name: "Alt Mitglied", email: null } as ParticipantSummary;
const role = { id: "r1", code: "reader", name: "Leser", is_system: true, permissions: [] } as unknown as RoleRead;

beforeEach(() => {
  vi.clearAllMocks();
  api.mockImplementation((url: string, init?: { method?: string }) => {
    const method = init?.method ?? "GET";
    if (url === "/api/auth/password-reset/available") return Promise.resolve({ enabled: true });
    if (url === "/api/participants" && method === "POST") return Promise.resolve(created);
    if (url === "/api/participants/p-new/invite") {
      return Promise.reject(new ApiError("Benutzerlimit erreicht", "conflict", 409, { code: "user_limit_reached", message: "Benutzerlimit erreicht" }));
    }
    if (url === "/api/participants/p-new") return Promise.resolve(created);
    if (url.startsWith("/api/participants?")) return Promise.resolve([created, existing]);
    return Promise.resolve(null);
  });
});

it("keeps the created person when the follow-up invite fails, so a retry cannot duplicate it", async () => {
  render(
    <ParticipantManager initialParticipants={[existing]} templates={[]} tenantId="t1" roles={[role]} tariffs={[]}
      permissions={{ access: true, financeRead: false, financeManage: false }} />,
  );
  fireEvent.click(screen.getAllByRole("button", { name: /Neues Mitglied/ })[0]);
  const dialog = await screen.findByRole("dialog");
  fireEvent.change(within(dialog).getByLabelText("Anzeigename"), { target: { value: "Neu Mitglied" } });
  fireEvent.change(within(dialog).getByLabelText("E-Mail"), { target: { value: "neu@example.org" } });
  const invite = await within(dialog).findByRole("checkbox", { name: /einladen/ });
  fireEvent.click(invite);
  fireEvent.click(within(dialog).getByRole("button", { name: "Erfassen und einladen" }));

  await waitFor(() => expect(toast).toHaveBeenCalled());
  // Angelegt ist angelegt: Dialog zu, Person in der Liste, Hinweis nennt die gescheiterte Einladung
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(screen.getAllByText("Neu Mitglied").length).toBeGreaterThan(0);
  expect(api.mock.calls.filter(([url, init]) => url === "/api/participants" && (init as { method?: string })?.method === "POST")).toHaveLength(1);
});

it("shows «Login gesperrt» instead of «Login aktiv» for former members with a login", async () => {
  const former = { ...created, id: "p-left", display_name: "Ehemals Mitglied", left_at: "2020-01-31", login_enabled: true, login_status: "active" } as unknown as ParticipantSummary;
  render(
    <ParticipantManager initialParticipants={[former]} templates={[]} tenantId="t1" roles={[role]} tariffs={[]}
      permissions={{ access: true, financeRead: false, financeManage: false }} />,
  );
  fireEvent.click(screen.getByRole("tab", { name: /Ausgetreten/ }));
  const row = (await screen.findByText("Ehemals Mitglied")).closest("tr") as HTMLElement;
  expect(within(row).getByText("Login gesperrt")).toBeInTheDocument();
  expect(within(row).queryByText("Login aktiv")).toBeNull();
});
