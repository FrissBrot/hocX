import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { apiFetch, toast } = vi.hoisted(() => ({ apiFetch: vi.fn(), toast: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ browserApiFetch: apiFetch, browserApiBaseUrl: "" }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => toast }));
vi.mock("@/components/settings/tenant-data-export", () => ({ TenantDataExportPanel: () => null }));

import { PrivacySettings } from "./privacy-settings";

const initialState = { statistics_per_person_public: false, privacy_notice_url: null };

describe("PrivacySettings › Datenschutzhinweise", () => {
  beforeEach(() => {
    apiFetch.mockReset();
    toast.mockReset();
  });

  function typeUrl(value: string) {
    fireEvent.change(screen.getByLabelText(/Link zu euren Datenschutzhinweisen/), { target: { value } });
  }

  it("lässt Links ohne Adresse oder mit Leerzeichen nicht speichern und sagt warum", () => {
    // Das Backend (privacy_settings._https_only) lehnt beides mit einem rohen deutschen
    // 422-Text ab («privacy_notice_url: Value error, …»), auch in en/fr/it.
    render(<PrivacySettings initialState={initialState} />);
    const save = screen.getByRole("button", { name: "Link speichern" });

    typeUrl("https://");
    expect(save).toBeDisabled();
    expect(screen.getByText(/vollständige Adresse/)).toBeInTheDocument();

    typeUrl("https://verein.example.ch/daten schutz");
    expect(save).toBeDisabled();

    typeUrl("https://verein.example.ch/datenschutz");
    expect(save).toBeEnabled();
    expect(screen.queryByText(/vollständige Adresse/)).toBeNull();
  });

  it("erlaubt das Entfernen eines gespeicherten Links (leeres Feld)", () => {
    render(<PrivacySettings initialState={{ ...initialState, privacy_notice_url: "https://verein.example.ch/ds" }} />);
    typeUrl("");
    expect(screen.getByRole("button", { name: "Link speichern" })).toBeEnabled();
  });
});
