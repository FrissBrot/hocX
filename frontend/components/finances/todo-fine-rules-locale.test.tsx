import fs from "node:fs";
import path from "node:path";

import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { FinanceAccount, FineTariffGroup } from "@/types/api";

// Vorschau «nach x Tagen» im Regel-Dialog in der UI-Sprache (fr-CH «12,50», nicht «12.50»)
vi.mock("next-intl", async (importOriginal) => {
  const actual = await importOriginal<typeof import("next-intl")>();
  const dir = path.join(process.cwd(), "messages", "fr");
  const messages = Object.fromEntries(
    fs.readdirSync(dir).filter((name) => name.endsWith(".json"))
      .map((name) => [name.slice(0, -".json".length), JSON.parse(fs.readFileSync(path.join(dir, name), "utf-8"))])
  );
  const cache = new Map<string, ReturnType<typeof actual.createTranslator>>();
  return {
    ...actual,
    useLocale: () => "fr",
    useTranslations: (namespace?: string) => {
      const key = namespace ?? "";
      if (!cache.has(key)) cache.set(key, actual.createTranslator({ locale: "fr", messages, namespace }));
      return cache.get(key);
    },
  };
});
vi.mock("@/lib/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/client")>()),
  browserApiFetch: vi.fn(() => new Promise(() => {})),
}));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => vi.fn() }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => vi.fn() }));

import { TodoFineRules } from "./todo-fine-rules";

const account = { id: "acc-1", name: "Caisse", currency_label: "CHF" } as unknown as FinanceAccount;
const tariff = { id: "tg-1", name: "Standard", is_default: true, member_count: 3 } as unknown as FineTariffGroup;

describe("TodoFineRules (UI-Sprache fr)", () => {
  it("zeigt die Betragsvorschau im Zahlenformat der UI-Sprache", () => {
    render(<TodoFineRules rules={[]} setRules={vi.fn()} tariffs={[tariff]} accounts={[account]} canManage onChanged={vi.fn(async () => {})} />);
    fireEvent.click(screen.getByRole("button", { name: "Ajouter une règle" }));
    fireEvent.change(screen.getByRole("spinbutton", { name: "Montant de base" }), { target: { value: "12.5" } });
    const table = screen.getByRole("table", { name: /./ });
    const preview = within(table).getAllByText(/12/).map((node) => node.textContent);
    expect(preview).toContain("12,50");
    expect(preview).not.toContain("12.50");
  });

  it("nimmt ohne Konto die Vereinswährung statt fest «CHF»", () => {
    render(<TodoFineRules rules={[]} setRules={vi.fn()} tariffs={[tariff]} accounts={[]} tenantCurrency="EUR" canManage onChanged={vi.fn(async () => {})} />);
    fireEvent.click(screen.getByRole("button", { name: "Ajouter une règle" }));
    const table = screen.getByRole("table", { name: /./ });
    expect(within(table).getAllByText("EUR").length).toBeGreaterThan(0);
    expect(within(table).queryByText("CHF")).toBeNull();
  });
});
