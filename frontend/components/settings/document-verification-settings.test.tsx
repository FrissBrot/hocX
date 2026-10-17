import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DocumentVerificationSettings, type DocumentVerificationState } from "./document-verification-settings";

const { apiFetch, toast, confirm } = vi.hoisted(() => ({ apiFetch: vi.fn(), toast: vi.fn(), confirm: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ browserApiFetch: apiFetch }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => toast }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => confirm }));

const base: DocumentVerificationState = {
  show_identity: false, show_newer_version: true, tenant_id: "t1", tenant_name: "Musikverein", has_logo: false,
  verified_at: null, revoked_at: null, revoked_reason: null, request: null, verify_base_url: "https://abgabe.example.ch/verify",
  has_verify_domain_feature: false, verify_domain: null,
};

describe("DocumentVerificationSettings", () => {
  beforeEach(() => {
    apiFetch.mockReset();
    toast.mockReset();
    confirm.mockReset();
  });

  it("toggles the public display and updates the preview", async () => {
    apiFetch.mockResolvedValue({ ...base, show_identity: true });
    render(<DocumentVerificationSettings initialState={base} />);
    expect(screen.queryByText("Musikverein")).not.toBeInTheDocument();
    expect(screen.getByText(/Herausgeber wird nicht angezeigt/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("switch", { name: /Name und Logo anzeigen/ }));
    await waitFor(() => expect(apiFetch).toHaveBeenCalledWith("/api/document-verification", expect.objectContaining({ method: "PATCH", body: JSON.stringify({ show_identity: true }) })));
    expect(await screen.findByText("Musikverein")).toBeInTheDocument();
    expect(screen.getByText("Herausgegeben von")).toBeInTheDocument();
    expect(screen.getByText("M")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Prüfseite öffnen" })).toHaveAttribute("href", "https://abgabe.example.ch/verify");
  });

  it("requests verification with a message and can withdraw it", async () => {
    apiFetch.mockResolvedValue({ ...base, request: { status: "pending", tenant_name: "Musikverein", message: "CHE-123", requested_at: "2026-10-14T10:00:00Z", decided_at: null, decision_note: null } });
    render(<DocumentVerificationSettings initialState={base} />);
    fireEvent.change(screen.getByLabelText("Nachricht an hocX (optional)"), { target: { value: "CHE-123" } });
    fireEvent.click(screen.getByRole("button", { name: "Verifizierung beantragen" }));
    await waitFor(() => expect(apiFetch).toHaveBeenCalledWith("/api/document-verification/request", expect.objectContaining({ method: "POST", body: JSON.stringify({ message: "CHE-123" }) })));
    expect(await screen.findByText("Antrag in Prüfung")).toBeInTheDocument();

    confirm.mockResolvedValue(true);
    apiFetch.mockResolvedValue({ ...base, request: { status: "withdrawn", tenant_name: "Musikverein", message: null, requested_at: "2026-10-14T10:00:00Z", decided_at: null, decision_note: null } });
    fireEvent.click(screen.getByRole("button", { name: "Antrag zurückziehen" }));
    await waitFor(() => expect(apiFetch).toHaveBeenLastCalledWith("/api/document-verification/request", expect.objectContaining({ method: "DELETE" })));
  });

  it("shows verification, badge preview and the hint after a rename", () => {
    const { rerender } = render(<DocumentVerificationSettings initialState={{ ...base, show_identity: true, verified_at: "2026-09-01T00:00:00Z" }} />);
    expect(screen.getByText("Verifiziert seit 01.09.2026")).toBeInTheDocument();
    expect(screen.getByText(/Verifizierte Organisation/)).toBeInTheDocument();
    expect(screen.getByText("Ändert sich der Name, wird die Verifizierung aufgehoben.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Verifizierung beantragen" })).not.toBeInTheDocument();
    rerender(<DocumentVerificationSettings key="renamed" initialState={{ ...base, revoked_at: "2026-10-01T00:00:00Z", revoked_reason: "name_changed" }} />);
    expect(screen.getByText(/weil sich der Name geändert hat/)).toBeInTheDocument();
  });

  it("shows the own verification domain with its status and the preview level", () => {
    const domain = { domain: "verify.musikverein.ch", status: "active" as const, is_healthy: true, in_use: true };
    const { rerender } = render(
      <DocumentVerificationSettings initialState={{ ...base, show_identity: true, has_verify_domain_feature: true, verify_domain: domain, verify_base_url: "https://verify.musikverein.ch/verify" }} />
    );
    expect(screen.getByText("verify.musikverein.ch")).toBeInTheDocument();
    expect(screen.getByText("Aktiv")).toBeInTheDocument();
    expect(screen.getByText("Prüf-Domain verifiziert")).toBeInTheDocument();
    expect(screen.getByText("verify.musikverein.ch/249A-0313")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Domains verwalten/ })).toHaveAttribute("href", "/tenant-settings/domains");
    expect(screen.getByRole("link", { name: "Prüfseite öffnen" })).toHaveAttribute("href", "https://verify.musikverein.ch/verify");

    // Name und Logo ausgeblendet: Domain bleibt eingerichtet, wird aber nicht verwendet
    rerender(
      <DocumentVerificationSettings key="hidden" initialState={{ ...base, has_verify_domain_feature: true, verify_domain: { ...domain, in_use: false } }} />
    );
    expect(screen.getByText("Inaktiv")).toBeInTheDocument();
    expect(screen.getByText(/erst verwendet, wenn Name und Logo/)).toBeInTheDocument();
    expect(screen.queryByText("Prüf-Domain verifiziert")).not.toBeInTheDocument();
    expect(screen.getByText("abgabe.example.ch/249A-0313")).toBeInTheDocument();
  });

  it("explains that the verification domain is not booked", () => {
    render(<DocumentVerificationSettings initialState={base} />);
    expect(screen.getByText("Nicht im Abo")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Prüf-Domain einrichten/ })).not.toBeInTheDocument();
    expect(screen.getByText("Immer aktiv")).toBeInTheDocument();
    expect(screen.getByText("Nicht verifiziert")).toBeInTheDocument();
  });

  it("offers to set up the domain when the feature is booked", () => {
    render(<DocumentVerificationSettings initialState={{ ...base, has_verify_domain_feature: true }} />);
    expect(screen.getByText("Nicht eingerichtet")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Prüf-Domain einrichten/ })).toHaveAttribute("href", "/tenant-settings/domains");
  });
});
