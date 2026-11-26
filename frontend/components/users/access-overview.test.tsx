// Zugriff › Wer hat Zugriff: Ein Austrittsdatum in der Vergangenheit sperrt den Login
// (AppUser.has_left), die Übersicht zeigte solche Konten aber als «Aktiv» und zählte sie bei
// «MFA fehlt» mit.
import { render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import type { UserSummary } from "@/types/api";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

import { AccessOverview } from "./access-overview";

function user(id: string, name: string, extra: Partial<UserSummary> = {}): UserSummary {
  return {
    id, first_name: null, last_name: null, display_name: name, email: `${id}@example.org`, preferred_language: "de",
    is_active: true, external_identity_json: {}, tenant_id: "t", tenant_name: "Verein", roles: [], login_enabled: true,
    mfa_enabled: false, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", ...extra,
  };
}

it("shows a login of a former member as inactive and leaves it out of «MFA missing»", () => {
  render(
    <AccessOverview
      users={[user("a", "Aktiv Person"), user("b", "Ausgetreten Person", { left_at: "2020-06-30" }), user("c", "Tritt aus", { left_at: "2999-12-31" })]}
      invites={[]} roles={[]} tenantRequiresMfa
    />,
  );
  const rowOf = (name: string) => screen.getByText(name).closest("tr") as HTMLElement;
  expect(within(rowOf("Ausgetreten Person")).getByText("Inaktiv")).toBeInTheDocument();
  expect(within(rowOf("Tritt aus")).getByText("Aktiv")).toBeInTheDocument();
  expect(within(rowOf("Aktiv Person")).getByText("Aktiv")).toBeInTheDocument();
  // MFA-Pflicht: nur die beiden, die sich anmelden können
  expect(screen.getByRole("tab", { name: /MFA/ })).toHaveTextContent("2");
});
