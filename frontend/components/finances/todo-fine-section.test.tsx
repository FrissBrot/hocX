import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { TodoFineEvaluation } from "@/types/api";

const api = vi.hoisted(() => vi.fn());
const toast = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/client", () => ({ browserApiFetch: (url: string, init?: { method?: string; body?: string }) => api(url, init) }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => toast }));

import { TodoFineSection } from "./todo-fine-section";
import { ruleAmount } from "./todo-fine-rules";

const rules = [
  { id: "r1", name: "Alle", sort_index: 0, is_active: true, applies_from: "2026-01-01", interval_days: 1, split_mode: "each", account_id: null,
    filter: { tags: [], task_package_ids: [], participant_ids: [], role_ids: [] }, rates: [{ tariff_group_id: "t1", base_amount: 0, interval_amount: 5 }] },
  { id: "r2", name: "Material", sort_index: 1, is_active: true, applies_from: "2026-01-01", interval_days: 1, split_mode: "each", account_id: null,
    filter: { tags: ["Material"], task_package_ids: [], participant_ids: [], role_ids: [] }, rates: [{ tariff_group_id: "t1", base_amount: 10, interval_amount: 2 }] },
  { id: "r3", name: "Vorstand", sort_index: 2, is_active: true, applies_from: "2026-01-01", interval_days: 7, split_mode: "each", account_id: null,
    filter: { tags: [], task_package_ids: [], participant_ids: [], role_ids: ["role"] }, rates: [{ tariff_group_id: "t1", base_amount: 20, interval_amount: 5 }] },
];

const conflict: TodoFineEvaluation = {
  state: "conflict", fine_mode: "auto", fine_rule_id: null, fine_fixed_amount: null, fine_split_mode: null,
  rule_id: null, rule_name: null, matching_rules: [{ id: "r1", name: "Alle" }, { id: "r2", name: "Material" }],
  due_date: "2026-11-01", days_late: 3, running: true, frozen: false, split_mode: null, lines: [], total: 0, can_manage: true,
  auto_rules: [{ id: "r1", name: "Alle" }, { id: "r2", name: "Material" }], currency: "CHF",
};

const ruleResult = (ruleId: string, name: string, amount: number): TodoFineEvaluation => ({
  ...conflict, state: "ok", fine_mode: "rule", fine_rule_id: ruleId, rule_name: name, matching_rules: [],
  lines: [{ participant_id: "p1", participant_name: "Anna", tariff_name: "Standard", amount }], total: amount,
});

beforeEach(() => {
  vi.clearAllMocks();
  api.mockImplementation((url: string, init?: { method?: string; body?: string }) => {
    if (url === "/api/todo-fines/rules") return Promise.resolve(rules);
    if (url === "/api/todo-fines/tariffs") return Promise.resolve([{ id: "t1", name: "Standard", is_default: true, sort_index: 0, member_count: 1, amount_late: null, amount_absent: null }]);
    if (url.endsWith("/fine/preview")) {
      const body = JSON.parse(init!.body!);
      if (body.fine_mode === "rule") return Promise.resolve(ruleResult(body.fine_rule_id, body.fine_rule_id === "r2" ? "Material" : "Alle", body.fine_rule_id === "r2" ? 16 : 15));
      if (body.fine_mode === "fixed") return Promise.resolve({ ...conflict, state: "ok", fine_mode: "fixed", split_mode: body.fine_split_mode, matching_rules: [],
        lines: [{ participant_id: "p1", participant_name: "Anna", tariff_name: null, amount: 20 }, { participant_id: "p2", participant_name: "Ben", tariff_name: null, amount: 20 }], total: 40 });
      return Promise.resolve({ ...conflict, state: body.fine_mode === "none" ? "none" : conflict.state });
    }
    if (init?.method === "PUT") return Promise.resolve(ruleResult("r2", "Material", 16));
    return Promise.resolve(conflict);
  });
});

it("shows the conflict with totals per rule and lets the cashier pick one", async () => {
  render(<TodoFineSection todoId="todo-1" />);
  expect(await screen.findByText("Mehrere Regeln passen. Welche soll gelten?")).toBeInTheDocument();
  const material = await screen.findByRole("button", { name: /Material.*16\.00/ });
  fireEvent.click(material);
  // Vorschau der gewählten Regel, gespeichert wird erst mit «Übernehmen» (Seite /fines)
  expect(await screen.findByText("Anna")).toBeInTheDocument();
  expect(screen.getByText(/Diese Regel gilt fest/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Übernehmen" }));
  await waitFor(() => expect(api.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(true));
  const put = api.mock.calls.find(([, init]) => init?.method === "PUT");
  expect(JSON.parse(put![1].body)).toEqual({ fine_mode: "rule", fine_rule_id: "r2", fine_fixed_amount: null, fine_split_mode: null });
});

it("offers all rules in the menu, marks matching ones and allows «Keine Busse»", async () => {
  const onDraftChange = vi.fn();
  render(<TodoFineSection todoId="todo-1" assigneeCount={1} onDraftChange={onDraftChange} />);
  fireEvent.click(await screen.findByRole("button", { name: /Regel · automatisch/ }));
  const menu = await screen.findByRole("menu");
  // Auch eine Regel, deren Filter nicht passt, lässt sich fest zuweisen
  const vorstand = within(menu).getByRole("menuitemradio", { name: /Vorstand/ });
  expect(vorstand).toHaveTextContent("CHF 20.00 + 5.00 pro 7 Tage");
  expect(within(within(menu).getByRole("menuitemradio", { name: /Material/ })).getByText("passt")).toBeInTheDocument();
  expect(within(vorstand).queryByText("passt")).not.toBeInTheDocument();
  fireEvent.click(within(menu).getByRole("menuitemradio", { name: /Keine Busse/ }));
  await waitFor(() => expect(onDraftChange).toHaveBeenLastCalledWith({ fine_mode: "none", fine_rule_id: null, fine_fixed_amount: null, fine_split_mode: null }));
  // Kein eigener Speicher-Knopf im Popup: es speichert mit «Speichern»
  expect(screen.queryByRole("button", { name: "Übernehmen" })).not.toBeInTheDocument();
});

it("a fixed amount overrides the rule and can be split among several people", async () => {
  const onDraftChange = vi.fn();
  render(<TodoFineSection todoId="todo-1" assigneeCount={2} onDraftChange={onDraftChange} />);
  fireEvent.change(await screen.findByLabelText("Fixbetrag"), { target: { value: "40" } });
  expect(screen.getByRole("button", { name: /Übersteuert durch Fixbetrag/ })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("radio", { name: "Aufteilen" }));
  await waitFor(() => expect(onDraftChange).toHaveBeenLastCalledWith({ fine_mode: "fixed", fine_rule_id: null, fine_fixed_amount: 40, fine_split_mode: "split" }));
  expect(await screen.findByText("Ben")).toBeInTheDocument();
  expect(screen.getByText("Fixbetrag geht vor. Feld leeren, um wieder nach Regel zu rechnen.")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Betrag leeren" }));
  await waitFor(() => expect(onDraftChange).toHaveBeenLastCalledWith(null));
});

it("hides the settings without finances.manage", async () => {
  api.mockResolvedValue({ ...conflict, state: "on_time", matching_rules: [], can_manage: false });
  render(<TodoFineSection todoId="todo-1" />);
  expect(await screen.findByText("Nicht verspätet.")).toBeInTheDocument();
  expect(screen.queryByLabelText("Fixbetrag")).not.toBeInTheDocument();
});

it("computes amounts like the backend (base + full intervals)", () => {
  expect(ruleAmount(5, 2, 2, 1)).toBe(5);
  expect(ruleAmount(5, 2, 2, 2)).toBe(7);
  expect(ruleAmount(5, 2, 2, 5)).toBe(9);
  expect(ruleAmount(5, 2, 1, 0)).toBe(0);
});

it("shows a frozen fine read-only with currency and explains it", async () => {
  api.mockResolvedValue({ ...conflict, state: "ok", running: false, frozen: true, matching_rules: [], rule_name: "Alle",
    lines: [{ participant_id: "p1", participant_name: "Anna", tariff_name: null, amount: 7.5 }], total: 7.5 });
  render(<TodoFineSection todoId="todo-1" readOnly />);
  expect(await screen.findByText("Eingefroren")).toBeInTheDocument();
  expect(screen.getAllByText(/7\.50/).length).toBeGreaterThan(0);
  expect(screen.getByText(/bleibt beim Wiedereröffnen/)).toBeInTheDocument();
  expect(screen.queryByLabelText("Fixbetrag")).not.toBeInTheDocument();
});

it("reports a failed load instead of silently hiding the section", async () => {
  api.mockRejectedValue(new Error("down"));
  render(<TodoFineSection todoId="todo-1" />);
  expect(await screen.findByText("Die Busse konnte nicht geladen werden.")).toBeInTheDocument();
});
