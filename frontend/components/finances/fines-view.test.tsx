import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FinesView } from "./fines-view";
import { buildRows, computeKpis, filterRows, groupByPerson } from "./fines-model";
import type { AttendanceFineListItem, FinanceAccount, TodoFineListItem } from "@/types/api";

const fetchMock = vi.fn();
vi.mock("@/lib/api/client", () => ({ browserApiFetch: (...args: unknown[]) => fetchMock(...args) }));
const confirmMock = vi.fn();
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => confirmMock }));
const toastMock = vi.fn();
vi.mock("@/contexts/toast-context", () => ({ useToast: () => toastMock }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }) }));

const YEAR = new Date().getFullYear();
const account: FinanceAccount = { id: "acc-1", name: "Bussenkasse", currency_label: "CHF", description: null, balance: 0, provisional_balance: 0, transaction_count: 0, created_at: "2026-01-01" };

function attendance(id: string, name: string, participant: string | null, overrides: Partial<AttendanceFineListItem> = {}): AttendanceFineListItem {
  return {
    id, protocol_id: `prot-${id}`, participant_id: participant, participant_name_snapshot: name, fine_type: "late", amount: 10,
    account_id: account.id, status: "pending", collected_at: null, collected_transaction_id: null, closed_in_protocol_id: null,
    collected_by_user_id: null, collected_by_display_name: null, can_reopen: false, created_at: `${YEAR}-01-01`,
    protocol_number: `${YEAR}.${id}`, protocol_date: `${YEAR}-03-01`, currency_label: "CHF", delete_requires_reason: false,
    ...overrides,
  };
}

function todo(id: string | null, name: string, participant: string, overrides: Partial<TodoFineListItem> = {}): TodoFineListItem {
  return {
    id, status: "pending", todo_id: `todo-${id ?? name}`, task: `Aufgabe ${id ?? name}`, participant_id: participant, participant_name: name,
    tariff_name: "Lernende", rule_name: "Material", matching_rules: [], due_date: `${YEAR}-11-01`, completed_on: null, days_late: 6,
    amount: 12, account_id: account.id, currency_label: "CHF", collected_at: null, collected_by_display_name: null,
    delete_comment: null, deleted_at: null, deleted_by_display_name: null, can_reopen: false,
    ...overrides,
  };
}

const melkLate = attendance("1", "Melk Staub", "p-melk", { amount: 20 });
const melkAbsent = attendance("2", "Melk Staub", "p-melk", { amount: 12, fine_type: "absent" });
const annaCollected = attendance("3", "Anna Muster", "p-anna", { status: "collected", collected_at: `${YEAR}-11-08T10:00:00Z`, collected_by_display_name: "Kassier", can_reopen: true });
const annaTodo = todo("tf-1", "Anna Muster", "p-anna");
const conflict = todo(null, "Beat Keller", "p-beat", { status: "conflict", matching_rules: [{ id: "r1", name: "Material" }, { id: "r2", name: "Protokoll" }], amount: 0 });

function renderView(props: Partial<Parameters<typeof FinesView>[0]> = {}) {
  return render(
    <FinesView
      initialFines={[melkLate, melkAbsent, annaCollected]}
      initialTodoFines={[annaTodo, conflict]}
      accounts={[account]}
      canWrite
      ownOnly={false}
      showAccountsTab
      currency="CHF"
      {...props}
    />,
  );
}

beforeEach(() => {
  fetchMock.mockReset();
  confirmMock.mockReset();
  toastMock.mockReset();
});

describe("fines-model", () => {
  const rows = buildRows([melkLate, melkAbsent, annaCollected], [annaTodo, conflict]);

  it("filtert nach Status, Suche und Konflikten", () => {
    expect(filterRows(rows, { status: "pending", search: "" })).toHaveLength(4);
    expect(filterRows(rows, { status: "collected", search: "" })).toHaveLength(1);
    expect(filterRows(rows, { status: "all", search: "aufgabe" }).map((r) => r.key)).toEqual(["t-tf-1", "t-conflict-todo-Beat Keller-p-beat-1"]);
    expect(filterRows(rows, { status: "pending", search: "", conflictsOnly: true })).toHaveLength(1);
  });

  it("gruppiert je Person (Präsenz- und Pendenzen-Bussen zusammen), meiste offene Summe zuerst", () => {
    const groups = groupByPerson(filterRows(rows, { status: "all", search: "" }), "de");
    expect(groups.map((g) => g.name)).toEqual(["Melk Staub", "Anna Muster", "Beat Keller"]);
    const anna = groups[1];
    expect(anna.rows).toHaveLength(2);
    expect(anna.tariff).toBe("Lernende");
    expect(anna.openCount).toBe(1);
    expect(anna.collectible).toHaveLength(1);
    // Konflikt: offen, aber nicht kassierbar
    expect(groups[2].collectible).toHaveLength(0);
  });

  it("rechnet Kennzahlen: offen, im Jahr kassiert, Personen", () => {
    expect(computeKpis(rows, YEAR)).toEqual({ openAmount: 44, openCount: 4, collectedAmount: 10, collectedCount: 1, peopleOpen: 3, peopleTotal: 3 });
    expect(computeKpis(rows, YEAR - 1).collectedCount).toBe(0);
  });

  it("zählt «im Jahr kassiert» nach Schweizer Zeit (Neujahr 00:30 gehört ins neue Jahr)", () => {
    // 31.12.2025 23:30 UTC = 01.01.2026 00:30 in Zürich - wie das Buchungsdatum im Backend
    const newYear = attendance("9", "Anna Muster", "p-anna", { status: "collected", collected_at: "2025-12-31T23:30:00Z" });
    const kpiRows = buildRows([newYear], []);
    expect(computeKpis(kpiRows, 2026).collectedCount).toBe(1);
    expect(computeKpis(kpiRows, 2025).collectedCount).toBe(0);
  });
});

describe("FinesView (Kasse › Bussen)", () => {
  it("zeigt Kennzahlen, Konflikt-Hinweis und Personen-Karten", () => {
    renderView();
    expect(screen.getByRole("heading", { level: 1, name: /Kasse/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Bussen\s*4/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("Personen mit offenen Bussen")).toBeInTheDocument();
    expect(screen.getByText("1 Pendenzen-Busse braucht eine Entscheidung.")).toBeInTheDocument();
    const melk = screen.getByRole("region", { name: "Melk Staub" });
    expect(within(melk).getByText("2 offen")).toBeInTheDocument();
    expect(within(melk).getByRole("button", { name: /Alle kassieren/ })).toBeInTheDocument();
    const anna = screen.getByRole("region", { name: "Anna Muster" });
    expect(within(anna).getByText("Lernende · 1 offen")).toBeInTheDocument();
    expect(within(anna).getByRole("button", { name: /^Kassieren$/ })).toBeInTheDocument();
  });

  it("filtert auf Konflikte und schaltet auf die Liste um", () => {
    renderView();
    fireEvent.click(screen.getByRole("button", { name: "Anzeigen" }));
    expect(screen.queryByRole("region", { name: "Melk Staub" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Regel wählen" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Liste" }));
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(2); // Kopf + Konflikt
    fireEvent.click(screen.getByRole("tab", { name: /Alle/ }));
    expect(screen.getAllByRole("row")).toHaveLength(6);
  });

  it("kassiert alle offenen Bussen einer Person einzeln und macht es über den Toast rückgängig", async () => {
    fetchMock.mockImplementation((url: string) => {
      const id = url.split("/")[3];
      const source = id === "1" ? melkLate : melkAbsent;
      if (url.endsWith("/collect")) return Promise.resolve({ ...source, status: "collected", collected_at: `${YEAR}-11-19T08:00:00Z`, can_reopen: true });
      return Promise.resolve({ ...source, status: "pending", can_reopen: false });
    });
    renderView();
    const melk = screen.getByRole("region", { name: "Melk Staub" });
    await act(async () => { fireEvent.click(within(melk).getByRole("button", { name: /Alle kassieren/ })); });
    expect(fetchMock).toHaveBeenCalledWith("/api/fines/1/collect", { method: "POST" });
    expect(fetchMock).toHaveBeenCalledWith("/api/fines/2/collect", { method: "POST" });
    const [message, tone, options] = toastMock.mock.calls[0];
    expect(message).toMatch(/^Melk Staub: CHF 32.00 kassiert$/);
    expect(tone).toBe("success");
    expect(options.action.label).toBe("Rückgängig");
    // Im Filter «Offen» ist Melk jetzt weg
    expect(screen.queryByRole("region", { name: "Melk Staub" })).not.toBeInTheDocument();

    fetchMock.mockClear();
    await act(async () => { options.action.onClick(); });
    expect(fetchMock).toHaveBeenCalledWith("/api/fines/1/reopen", { method: "POST" });
    expect(fetchMock).toHaveBeenCalledWith("/api/fines/2/reopen", { method: "POST" });
    // Rückgängig fragt nicht nach (die Person hat eben selbst kassiert)
    expect(confirmMock).not.toHaveBeenCalled();
    expect(screen.getByRole("region", { name: "Melk Staub" })).toBeInTheDocument();
  });

  it("kassiert eine Pendenzen-Busse über den Haken", async () => {
    fetchMock.mockResolvedValue({ ...annaTodo, status: "collected", collected_at: `${YEAR}-11-19T08:00:00Z`, can_reopen: true });
    renderView();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Busse von Anna Muster als kassiert markieren" })); });
    expect(fetchMock).toHaveBeenCalledWith("/api/todo-fines/tf-1/collect", { method: "POST" });
    expect(toastMock.mock.calls[0][0]).toBe("Anna Muster: CHF 12.00 kassiert");
  });

  it("Pendenzen-Busse ohne Konto: übersetzte Meldung statt rohem Backend-Text", async () => {
    // Backend (todo_fines.collect): 409 mit Code no_account und deutschem Text, der in en/fr/it sonst roh erschien
    fetchMock.mockRejectedValue(Object.assign(new Error("Kein Konto für diese Busse festgelegt"), {
      status: 409, detail: { code: "no_account", message: "Kein Konto für diese Busse festgelegt" },
    }));
    renderView();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Busse von Anna Muster als kassiert markieren" })); });
    expect(toastMock).toHaveBeenCalledWith("Für diese Busse ist kein Konto festgelegt. Lege unter «Bussen-Regeln» ein Konto fest.", "error");
  });

  it("Pendenzen-Busse mit geändertem Status: Konfliktmeldung statt englischem Backend-Text", async () => {
    fetchMock.mockRejectedValue(Object.assign(new Error("Fine status does not allow this action"), {
      status: 409, detail: "Fine status does not allow this action",
    }));
    renderView();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Busse von Anna Muster als kassiert markieren" })); });
    expect(toastMock).toHaveBeenCalledWith("Die Änderung ist nicht möglich, weil sich die Daten inzwischen geändert haben. Bitte neu laden.", "error");
  });

  it("zeigt Leerzustände für «Alles kassiert» und «Keine Treffer»", () => {
    renderView({ initialFines: [annaCollected], initialTodoFines: [] });
    expect(screen.getByText("Alles kassiert.")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Person, Protokoll oder Pendenz" }), { target: { value: "xyz" } });
    expect(screen.getByText("Keine Treffer.")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Person, Protokoll oder Pendenz" }), { target: { value: "" } });
    fireEvent.click(screen.getByRole("tab", { name: /Kassiert/ }));
    expect(screen.getByRole("region", { name: "Anna Muster" })).toBeInTheDocument();
  });

  it("ohne Bussen: Leerzustand mit «+ Busse»; ohne fines.manage keine Aktionen", () => {
    const { unmount } = renderView({ initialFines: [], initialTodoFines: [] });
    expect(screen.getByText("Noch keine Bussen erfasst")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "+ Busse" })).toBeInTheDocument();
    unmount();
    renderView({ canWrite: false, ownOnly: true, showAccountsTab: false });
    expect(screen.queryByRole("button", { name: /kassieren/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Löschen" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "+ Busse" })).not.toBeInTheDocument();
    // Ohne finances.read kein Reiter «Konten»
    expect(screen.queryByRole("tab", { name: "Konten" })).not.toBeInTheDocument();
  });
});
