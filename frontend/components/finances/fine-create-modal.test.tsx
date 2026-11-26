import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { FinanceAccount } from "@/types/api";

// Stabile Übersetzer je Namespace (wie next-intl selbst): der globale Test-Mock erzeugt bei jedem
// Render ein neues `t`, das den Lade-Effekt (Abhängigkeit `t`) sonst endlos neu auslöst.
vi.mock("next-intl", async (importOriginal) => {
  const actual = await importOriginal<typeof import("next-intl")>();
  const fs = await import("node:fs");
  const path = await import("node:path");
  const dir = path.join(process.cwd(), "messages", "de");
  const messages = Object.fromEntries(
    fs.readdirSync(dir).filter((name) => name.endsWith(".json"))
      .map((name) => [name.slice(0, -".json".length), JSON.parse(fs.readFileSync(path.join(dir, name), "utf-8"))])
  );
  const cache = new Map<string, ReturnType<typeof actual.createTranslator>>();
  return {
    ...actual,
    useLocale: () => "de",
    useTranslations: (namespace?: string) => {
      const key = namespace ?? "";
      if (!cache.has(key)) cache.set(key, actual.createTranslator({ locale: "de", messages, namespace }));
      return cache.get(key);
    },
  };
});

const fetchMock = vi.fn();
vi.mock("@/lib/api/client", () => ({ browserApiFetch: (...args: unknown[]) => fetchMock(...args) }));
const toastMock = vi.fn();
vi.mock("@/contexts/toast-context", () => ({ useToast: () => toastMock }));
// Auswahl vereinfacht: je Option ein Knopf (der echte SearchableSelect ist hier nicht Gegenstand)
vi.mock("@/components/ui/searchable-select", () => ({
  SearchableSelect: <T,>({ options, getLabel, onChange }: { options: T[]; getLabel: (o: T) => string; onChange: (o: T) => void }) => (
    <div>{options.map((option) => <button type="button" key={getLabel(option)} onClick={() => onChange(option)}>{getLabel(option)}</button>)}</div>
  ),
}));

import { FineCreateModal } from "./fine-create-modal";

const account = { id: "acc-1", name: "Bussenkasse", currency_label: "CHF" } as unknown as FinanceAccount;

beforeEach(() => {
  fetchMock.mockReset();
  toastMock.mockReset();
});

describe("FineCreateModal", () => {
  it("meldet eine doppelte Busse übersetzt (mit Typ-Bezeichnung statt rohem Wert 'absent')", async () => {
    fetchMock.mockImplementation((path: string, init?: RequestInit) => {
      if (path.startsWith("/api/protocols")) return Promise.resolve([{ id: "p-1", protocol_number: "2026.1", title: null, protocol_date: "2026-11-01" }]);
      if (path.startsWith("/api/participants")) return Promise.resolve([{ id: "pa-1", display_name: "Anna Muster", is_active: true }]);
      if (path === "/api/fines" && init?.method === "POST") {
        const message = "Für Anna Muster existiert in diesem Protokoll bereits eine Busse vom Typ 'absent'";
        return Promise.reject(Object.assign(new Error(message), { status: 409, detail: { code: "duplicate_fine", message } }));
      }
      return Promise.resolve([]);
    });
    render(<FineCreateModal open accounts={[account]} onClose={vi.fn()} onCreated={vi.fn()} />);
    await act(async () => {});

    fireEvent.click(screen.getByRole("button", { name: "2026.1" }));
    fireEvent.click(screen.getByRole("button", { name: "Anna Muster" }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "absent" } });
    fireEvent.change(screen.getByPlaceholderText("0.00"), { target: { value: "5" } });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Erfassen" })); });

    expect(toastMock).toHaveBeenCalledWith("Anna Muster hat in diesem Protokoll bereits eine Busse «Unentschuldigt».", "error");
  });
});
