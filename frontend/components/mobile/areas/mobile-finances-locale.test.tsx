import fs from "node:fs";
import path from "node:path";

import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { FinanceAccount, FinanceTransaction } from "@/types/api";

// Mobile Kasse mit französischer UI-Sprache: Beträge müssen wie auf dem Desktop im Zahlenformat
// der UI-Sprache erscheinen (fr-CH «1 234,50»), nicht fest im de-CH-Format «1’234.50».
vi.mock("next-intl", async (importOriginal) => {
  const actual = await importOriginal<typeof import("next-intl")>();
  const dir = path.join(process.cwd(), "messages", "fr");
  const messages = Object.fromEntries(
    fs
      .readdirSync(dir)
      .filter((name) => name.endsWith(".json"))
      .map((name) => [name.slice(0, -".json".length), JSON.parse(fs.readFileSync(path.join(dir, name), "utf-8"))])
  );
  return { ...actual, useTranslations: (namespace?: string) => actual.createTranslator({ locale: "fr", messages, namespace }), useLocale: () => "fr" };
});

const { apiFetch } = vi.hoisted(() => ({ apiFetch: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ browserApiFetch: apiFetch }));
vi.mock("@/components/mobile/mobile-shell", () => ({ useOpenMore: () => vi.fn() }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => vi.fn() }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => vi.fn() }));

import { MobileFinances } from "./mobile-finances";

const frNumber = (value: number) => new Intl.NumberFormat("fr-CH", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);

describe("MobileFinances (UI-Sprache fr)", () => {
  it("formatiert Saldo, provisorischen Saldo und Buchungen in der UI-Sprache", async () => {
    const account = { id: "a", name: "Caisse", balance: 1234.5, provisional_balance: 1850, transaction_count: 1, currency_label: "CHF" } as unknown as FinanceAccount;
    const tx = { id: "t1", description: "Cotisation", amount: 2500, transaction_date: "2026-10-01" } as unknown as FinanceTransaction;
    apiFetch.mockResolvedValue([tx]);

    const { container } = render(<MobileFinances initialAccounts={[account]} currency="CHF" canWrite={false} />);
    await act(async () => {});

    expect(screen.getByText(`CHF ${frNumber(1234.5)}`)).toBeInTheDocument();
    // Provisorischer Saldo als übersetzter Satz (ICU-Variable statt Verkettung), wie auf dem Desktop
    expect(screen.getByText(`+ CHF ${frNumber(1850)} ouvert`)).toBeInTheDocument();
    expect(container.textContent).toContain(frNumber(2500));
    expect(container.textContent).not.toContain("1’234.50");
  });
});
