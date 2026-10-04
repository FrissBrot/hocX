import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FinancesView } from "./finances-view";
import type { FinanceAccount, FinanceTransaction } from "@/types/api";

const fetchMock = vi.fn();
vi.mock("@/lib/api/client", () => ({ browserApiFetch: (...args: unknown[]) => fetchMock(...args) }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => vi.fn() }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => vi.fn() }));

const account: FinanceAccount = { id: "account-1", name: "Vereinskasse", currency_label: "CHF", description: null, balance: 8240.5, provisional_balance: 1850, transaction_count: 1, created_at: "2026-10-04" };
const expense: FinanceTransaction = { id: "tx-1", account_id: account.id, amount: -30, description: "Raummiete", transaction_date: "2026-09-30", protocol_id: null, created_at: "2026-09-30", running_balance: 8240.5 };

async function openForm(transactions: FinanceTransaction[] = []) {
  fetchMock.mockImplementation((url: string) => Promise.resolve(url === "/api/finance/accounts" ? [account] : transactions));
  render(<FinancesView initialAccounts={[account]} canWrite />);
  fireEvent.click(screen.getByRole("button", { name: /Vereinskasse/ }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalled());
  fireEvent.click(screen.getByRole("button", { name: "+ Transaktion" }));
}

beforeEach(() => fetchMock.mockReset());

describe("Transaktionsformular", () => {
  it.each([["Einnahme", 50.5], ["Ausgabe", -50.5]])("bucht %s mit dem passenden Vorzeichen", async (direction, expected) => {
    await openForm();
    fireEvent.click(screen.getByRole("tab", { name: direction }));
    fireEvent.change(screen.getByRole("textbox", { name: "Betrag (CHF)" }), { target: { value: "50,50" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Beschreibung" }), { target: { value: "Raummiete" } });
    fireEvent.click(screen.getByRole("button", { name: "Hinzufügen" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(`/api/finance/accounts/${account.id}/transactions`, expect.objectContaining({ method: "POST", body: expect.any(String) })));
    const call = fetchMock.mock.calls.find(([, options]) => options?.method === "POST");
    expect(JSON.parse(call![1].body).amount).toBe(expected);
  });

  it("übernimmt beim Bearbeiten einer Ausgabe Auswahl und positiven Betrag", async () => {
    await openForm([expense]);
    fireEvent.click(screen.getByRole("button", { name: "Abbrechen" }));
    await screen.findByText("Raummiete");
    fireEvent.click(screen.getAllByRole("button", { name: "Bearbeiten" }).at(-1)!);
    expect(screen.getByRole("tab", { name: "Ausgabe" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("textbox", { name: "Betrag (CHF)" })).toHaveValue("30");
    fireEvent.click(screen.getByRole("button", { name: "Aktualisieren" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/finance/transactions/tx-1", expect.objectContaining({ method: "PATCH" })));
    const call = fetchMock.mock.calls.find(([, options]) => options?.method === "PATCH");
    expect(JSON.parse(call![1].body).amount).toBe(-30);
  });

  it("verhindert ungültige Beträge und setzt das Datum über Heute zurück", async () => {
    await openForm();
    fireEvent.change(screen.getByRole("textbox", { name: "Beschreibung" }), { target: { value: "Raummiete" } });
    const amount = screen.getByRole("textbox", { name: "Betrag (CHF)" });
    for (const value of ["0", "-30", "abc", "50abc", "Infinity"]) {
      fireEvent.change(amount, { target: { value } });
      expect(screen.getByRole("button", { name: "Hinzufügen" })).toBeDisabled();
    }
    const date = screen.getByRole("textbox", { name: "Datum" });
    const original = (date as HTMLInputElement).value;
    fireEvent.change(date, { target: { value: "30.09.2026" } });
    fireEvent.click(screen.getByRole("button", { name: "Heute" }));
    expect(date).toHaveValue(original);
  });
});
