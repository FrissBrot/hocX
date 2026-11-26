import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AttendanceFineListItem, FinanceAccount, FinanceTransaction } from "@/types/api";

const { apiFetch } = vi.hoisted(() => ({ apiFetch: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ browserApiFetch: apiFetch }));
vi.mock("@/components/mobile/mobile-shell", () => ({ useOpenMore: () => vi.fn() }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => vi.fn() }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => vi.fn() }));

import { MobileFinances, MobileFines } from "./mobile-finances";
import { dateParts } from "@/components/mobile/mobile-utils";

function account(id: string, name: string): FinanceAccount {
  return { id, name, balance: 0, provisional_balance: 0, transaction_count: 1, currency_label: "CHF" } as unknown as FinanceAccount;
}
function tx(id: string, description: string): FinanceTransaction {
  return { id, description, amount: 10, transaction_date: "2026-10-01" } as unknown as FinanceTransaction;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}

describe("MobileFinances", () => {
  it("zeigt nach schnellem Kontowechsel nie die verspaetete Antwort des vorigen Kontos (Audit MAIN-FE-005)", async () => {
    const slowA = deferred<FinanceTransaction[]>();
    const fastB = deferred<FinanceTransaction[]>();
    apiFetch.mockImplementation((path: string) => {
      if (path.includes("/accounts/a/")) return slowA.promise;
      if (path.includes("/accounts/b/")) return fastB.promise;
      return Promise.resolve([]);
    });

    render(<MobileFinances initialAccounts={[account("a", "Kasse A"), account("b", "Kasse B")]} canWrite={false} />);
    fireEvent.click(screen.getByText("Kasse B"));

    // Konto B antwortet zuerst, die langsamere Antwort von Konto A kommt danach.
    await act(async () => { fastB.resolve([tx("tb", "Buchung B")]); });
    await act(async () => { slowA.resolve([tx("ta", "Buchung A")]); });

    expect(screen.getByText("Buchung B")).toBeInTheDocument();
    expect(screen.queryByText("Buchung A")).not.toBeInTheDocument();
  });

  it("zeigt das Kassierdatum als Schweizer Kalendertag (UTC-Zeitstempel kurz nach Mitternacht)", async () => {
    // 07.11. 23:30 UTC = 08.11. 00:30 in Zürich
    const fine = {
      id: "f-1", protocol_id: "p-1", participant_id: "pa-1", participant_name_snapshot: "Nina Nacht", fine_type: "late", amount: 10,
      account_id: "a", status: "collected", collected_at: "2026-11-07T23:30:00+00:00", can_reopen: false, protocol_number: "2026.1",
      protocol_date: "2026-11-01", currency_label: "CHF", delete_requires_reason: false,
    } as unknown as AttendanceFineListItem;
    apiFetch.mockImplementation((path: string) => Promise.resolve(path.startsWith("/api/fines") ? [fine] : []));
    render(<MobileFines initialFines={[fine]} accounts={[]} canWrite={false} ownOnly={false} />);
    await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: /Kassiert/ }));
    fireEvent.click(screen.getByText("Nina Nacht"));
    expect(screen.getByText(`Kassiert · ${dateParts.dayMonth("2026-11-08", "de")}`)).toBeInTheDocument();
  });
});
