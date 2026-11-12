import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FinesView } from "./fines-view";
import type { TodoFineListItem } from "@/types/api";

const fetchMock = vi.fn();
vi.mock("@/lib/api/client", () => ({ browserApiFetch: (...args: unknown[]) => fetchMock(...args) }));
const confirmMock = vi.fn();
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => confirmMock }));
const toastMock = vi.fn();
vi.mock("@/contexts/toast-context", () => ({ useToast: () => toastMock }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }) }));

const collected: TodoFineListItem = {
  id: "tf-1", status: "collected", todo_id: "t-1", task: "Protokoll schreiben", participant_id: "p-1", participant_name: "Anna",
  tariff_name: null, rule_name: "Standard", matching_rules: [], due_date: "2026-11-01", completed_on: "2026-11-05", days_late: 4,
  amount: 12.5, account_id: "a-1", currency_label: "CHF", collected_at: "2026-11-06T10:00:00Z", collected_by_display_name: "Kasse",
  delete_comment: null, deleted_at: null, deleted_by_display_name: null, can_reopen: true,
};

function renderView() {
  render(<FinesView initialFines={[]} initialTodoFines={[collected]} accounts={[]} canWrite ownOnly={false} />);
  fireEvent.click(screen.getByRole("tab", { name: /Kassiert/ }));
}

beforeEach(() => {
  fetchMock.mockReset();
  confirmMock.mockReset();
  toastMock.mockReset();
});

describe("FinesView: Wieder öffnen einer einkassierten Pendenzen-Busse", () => {
  it("fragt nach (Buchung wird gelöscht) und bricht bei Nein ab", async () => {
    confirmMock.mockResolvedValue(false);
    renderView();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Rückgängig" })); });
    expect(confirmMock).toHaveBeenCalledTimes(1);
    const options = confirmMock.mock.calls[0][0];
    expect(options.tone).toBe("danger");
    expect(options.message).toContain("Anna");
    expect(options.message).toContain("Buchung");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("öffnet nach Bestätigung wieder und meldet den Erfolg", async () => {
    confirmMock.mockResolvedValue(true);
    fetchMock.mockResolvedValue({ ...collected, status: "pending", can_reopen: false });
    renderView();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Rückgängig" })); });
    expect(fetchMock).toHaveBeenCalledWith("/api/todo-fines/tf-1/reopen", { method: "POST" });
    expect(toastMock).toHaveBeenCalledWith("Busse wieder geöffnet, Buchung gelöscht.", "success");
  });
});
