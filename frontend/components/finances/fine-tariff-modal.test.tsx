import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { FineTariff } from "@/types/api";

const fetchMock = vi.fn();
vi.mock("@/lib/api/client", () => ({ browserApiFetch: (...args: unknown[]) => fetchMock(...args) }));
const toastMock = vi.fn();
vi.mock("@/contexts/toast-context", () => ({ useToast: () => toastMock }));
vi.mock("@/components/ui/searchable-select", () => ({ SearchableSelect: () => null }));

import { FineTariffModal } from "./fine-tariff-modal";

const tariff = { account_id: "acc-1", amount_late: 5, amount_absent: 10 } as FineTariff;
const accounts = [{ id: "acc-1", name: "Kasse", currency_label: "CHF" }] as never;

function renderModal() {
  return render(<FineTariffModal open tariff={tariff} accounts={accounts} onClose={vi.fn()} onSaved={vi.fn()} />);
}

beforeEach(() => {
  fetchMock.mockReset();
  toastMock.mockReset();
});

describe("FineTariffModal", () => {
  it("lässt Beträge über 100 000 nicht speichern und nennt den erlaubten Bereich (Backend antwortete 422 roh)", async () => {
    renderModal();
    const [late] = screen.getAllByRole("spinbutton");
    fireEvent.change(late, { target: { value: "150000" } });
    expect(screen.getByText(/^Betrag von 0 bis 100['’]000\.00$/)).toBeInTheDocument();
    expect(late).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("button", { name: "Speichern" })).toBeDisabled();

    fireEvent.change(late, { target: { value: "100000" } });
    expect(screen.queryByText(/^Betrag von 0 bis 100['’]000\.00$/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Speichern" })).toBeEnabled();
  });

  it("zeigt bei einem 422 die übersetzte Meldung statt des Pydantic-Texts", async () => {
    fetchMock.mockRejectedValue(Object.assign(new Error("amount_late: Input should be less than or equal to 100000"), {
      status: 422, detail: [{ loc: ["body", "amount_late"], msg: "Input should be less than or equal to 100000" }],
    }));
    renderModal();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Speichern" })); });
    expect(toastMock).toHaveBeenCalledWith("Bitte die Eingaben prüfen (Betrag und Beschreibung).", "error");
  });
});
