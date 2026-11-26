import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { FineTariffGroup } from "@/types/api";

const fetchMock = vi.fn();
vi.mock("@/lib/api/client", () => ({ browserApiFetch: (...args: unknown[]) => fetchMock(...args) }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => vi.fn() }));
const toastMock = vi.fn();
vi.mock("@/contexts/toast-context", () => ({ useToast: () => toastMock }));

import { TodoFineTariffs } from "./todo-fine-tariffs";

const learners: FineTariffGroup = { id: "tg-1", name: "Lernende", sort_index: 0, is_default: true, member_count: 2, amount_late: null, amount_absent: null };

beforeEach(() => {
  fetchMock.mockReset();
  toastMock.mockReset();
});

describe("TodoFineTariffs", () => {
  it("meldet einen doppelten Tarifnamen übersetzt statt «Tariff name already exists»", async () => {
    fetchMock.mockImplementation((path: string, init?: RequestInit) => {
      if (path === "/api/todo-fines/tariffs" && init?.method === "POST") {
        return Promise.reject(Object.assign(new Error("Tariff name already exists"), {
          status: 409, detail: { code: "tariff_name_taken", message: "Tariff name already exists" },
        }));
      }
      return Promise.resolve([]);
    });
    render(<TodoFineTariffs tariffs={[learners]} setTariffs={vi.fn()} canManage currency="CHF" onChanged={vi.fn(async () => {})} />);
    await act(async () => {});

    fireEvent.click(screen.getByRole("button", { name: /Tarif hinzufügen/ }));
    fireEvent.change(screen.getByRole("textbox", { name: /^Name/ }), { target: { value: "Lernende" } });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Speichern" })); });

    expect(toastMock).toHaveBeenCalledWith("Es gibt schon einen Tarif «Lernende». Bitte einen anderen Namen wählen.", "error");
  });
});
