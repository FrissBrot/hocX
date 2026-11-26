import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { apiFetch, toast, confirm } = vi.hoisted(() => ({ apiFetch: vi.fn(), toast: vi.fn(), confirm: vi.fn() }));
vi.mock("@/lib/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/client")>();
  return { ...actual, browserApiFetch: apiFetch };
});
vi.mock("@/contexts/toast-context", () => ({ useToast: () => toast }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => confirm }));

import { ApiError } from "@/lib/api/client";
import type { TenantDomain } from "@/types/api";

import { DomainWizardModal } from "./domain-wizard-modal";

const pending: TenantDomain = {
  id: "d1", domain: "app.verein.example", purpose: "app", status: "pending", verification_token: "tok",
  challenge_record_name: "_hocx-challenge.app.verein.example", target_host: "app.hocx.example", verified_at: null,
  is_healthy: false, last_checked_at: null, replaces_domain: null,
} as TenantDomain;

function renderWizard(domain: TenantDomain | null = null) {
  return render(<DomainWizardModal open onClose={vi.fn()} tenantId="t1" domain={domain} purposes={["app"]} onChanged={vi.fn()} />);
}

describe("DomainWizardModal › Tastatur und Fehler", () => {
  beforeEach(() => {
    apiFetch.mockReset();
  });

  it("legt die Domain mit Enter im Domainfeld an", async () => {
    apiFetch.mockResolvedValue(pending);
    renderWizard();
    const input = screen.getByRole("textbox", { name: "Domain" });
    fireEvent.change(input, { target: { value: "app.verein.example" } });
    fireEvent.submit(input);
    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith("/api/tenants/t1/domains", expect.objectContaining({ method: "POST" }))
    );
  });

  it("sagt einen Prüffehler (TXT fehlt) als Alarm an", async () => {
    apiFetch.mockRejectedValue(
      new ApiError("Der TXT-Eintrag fehlt", "validation", 400, { code: "domain_txt_missing", record: "_hocx-challenge.app.verein.example" })
    );
    renderWizard(pending);
    fireEvent.click(screen.getByRole("button", { name: "Jetzt verifizieren" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/TXT-Eintrag _hocx-challenge\.app\.verein\.example/);
  });
});
