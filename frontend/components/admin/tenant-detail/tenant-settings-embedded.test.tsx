import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const browserApiFetchMock = vi.fn();
vi.mock("@/lib/api/client", () => ({
  browserApiFetch: (...args: unknown[]) => browserApiFetchMock(...args),
}));

import { ConfirmProvider } from "@/contexts/confirm-context";
import { ToastProvider } from "@/contexts/toast-context";
import { AdminTenantSettingsModal } from "@/components/admin/admin-tenant-settings-modal";
import { TenantStatusBadges } from "@/components/admin/tenant-detail/tenant-status-badges";
import type { AdminTenantSummary } from "@/types/api";

const TENANT = {
  id: "7f3a0000-0000-4000-8000-000000000001",
  name: "Verein X",
  profile_image_path: null,
  profile_image_url: null,
  participant_count: 3,
  user_count: 2,
  created_at: "2026-01-01T00:00:00Z",
  storage_used_bytes: 0,
  storage_quota_bytes: null,
  enabled_features: [],
  read_only_features: ["finance"],
  addon_features: [],
  plan_code: null,
  plan_name: null,
  billing_cycle: "monthly",
  user_limit_override: null,
  effective_user_limit: null,
  plan_storage_bytes: null,
  package_storage_bytes: 0,
  effective_storage_quota_bytes: null,
  assigned_storage_packages: [],
  discount_percent: 0,
  billing_note: null,
  billing_start_date: null,
  contract_ends_on: null,
  show_on_website: false,
  identity_verified_at: null,
} as unknown as AdminTenantSummary;

function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ToastProvider>
      <ConfirmProvider>{children}</ConfirmProvider>
    </ToastProvider>
  );
}

describe("Mandanten-Detailseite: eingebettete Einstellungen", () => {
  beforeEach(() => {
    browserApiFetchMock.mockReset();
    browserApiFetchMock.mockResolvedValue([]);
  });

  it("zeigt Stammdaten ohne Dialog und lädt keine (auditierte) Benutzerliste", async () => {
    render(<Providers><AdminTenantSettingsModal open onClose={() => undefined} tenant={TENANT} onSaved={() => undefined} embeddedTab="stammdaten" /></Providers>);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByDisplayValue("Verein X")).toBeInTheDocument();
    await waitFor(() => expect(browserApiFetchMock).not.toHaveBeenCalledWith(expect.stringContaining("/users")));
  });

  it("sperrt Formular und Speichern für support (readOnly)", () => {
    render(<Providers><AdminTenantSettingsModal open onClose={() => undefined} tenant={TENANT} onSaved={() => undefined} embeddedTab="stammdaten" readOnly /></Providers>);
    expect(screen.getByDisplayValue("Verein X")).toBeDisabled();
    for (const button of screen.getAllByRole("button")) {
      if (button.getAttribute("type") === "submit") expect(button).toBeDisabled();
    }
  });

  it("zeigt abgeleitete Status als Text-Badges", () => {
    render(<TenantStatusBadges tenant={TENANT} />);
    expect(screen.getByText("Nur-Lesen")).toBeInTheDocument();
    expect(screen.getByText("Nicht verifiziert")).toBeInTheDocument();
    expect(screen.queryByText("Aktiv")).not.toBeInTheDocument();
  });
});
