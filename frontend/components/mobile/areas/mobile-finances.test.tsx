import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { FinanceAccount, FinanceTransaction } from "@/types/api";

const { apiFetch } = vi.hoisted(() => ({ apiFetch: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ browserApiFetch: apiFetch }));
vi.mock("@/components/mobile/mobile-shell", () => ({ useOpenMore: () => vi.fn() }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => vi.fn() }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => vi.fn() }));

import { MobileFinances } from "./mobile-finances";

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
});
