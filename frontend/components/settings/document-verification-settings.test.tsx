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
    fireEvent.click(screen.getByLabelText("Name und Logo auf der Prüfseite anzeigen"));
    await waitFor(() => expect(apiFetch).toHaveBeenCalledWith("/api/document-verification", expect.objectContaining({ method: "PATCH", body: JSON.stringify({ show_identity: true }) })));
    expect(await screen.findByText("Erstellt im hocX-Konto von Musikverein.")).toBeInTheDocument();
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
    expect(screen.getByText("Verifizierte Organisation")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Verifizierung beantragen" })).not.toBeInTheDocument();
    rerender(<DocumentVerificationSettings key="renamed" initialState={{ ...base, revoked_at: "2026-10-01T00:00:00Z", revoked_reason: "name_changed" }} />);
    expect(screen.getByText(/weil sich der Name geändert hat/)).toBeInTheDocument();
  });
});
