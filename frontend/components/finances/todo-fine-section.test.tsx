import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { TodoFineEvaluation } from "@/types/api";

const api = vi.hoisted(() => vi.fn());
const toast = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/client", () => ({ browserApiFetch: (url: string, init?: { method?: string; body?: string }) => api(url, init) }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => toast }));

import { TodoFineSection } from "./todo-fine-section";
import { ruleAmount } from "./todo-fine-rules";

const conflict: TodoFineEvaluation = {
  state: "conflict", fine_mode: "auto", fine_rule_id: null, fine_fixed_amount: null, fine_split_mode: null,
  rule_id: null, rule_name: null, matching_rules: [{ id: "r1", name: "Alle" }, { id: "r2", name: "Material" }],
  due_date: "2026-11-01", days_late: 3, running: true, frozen: false, split_mode: null, lines: [], total: 0, can_manage: true,
};

beforeEach(() => {
  vi.clearAllMocks();
  api.mockImplementation((url: string, init?: { method?: string }) => {
    if (url === "/api/todo-fines/rules") return Promise.resolve([{ id: "r1", name: "Alle" }, { id: "r2", name: "Material" }]);
    if (init?.method === "PUT") {
      return Promise.resolve({ ...conflict, state: "ok", fine_mode: "rule", fine_rule_id: "r2", rule_name: "Material", matching_rules: [],
        lines: [{ participant_id: "p1", participant_name: "Anna", tariff_name: "Lernende", amount: 5 }] });
    }
    return Promise.resolve(conflict);
  });
});

it("warns about several matching rules and lets the cashier pick one", async () => {
  render(<TodoFineSection todoId="todo-1" />);
  expect(await screen.findByText(/Mehrere Regeln passen \(Alle, Material\)/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Busse festlegen"), { target: { value: "rule" } });
  await waitFor(() => expect(screen.getByLabelText("Regel")).toBeInTheDocument());
  fireEvent.change(screen.getByLabelText("Regel"), { target: { value: "r2" } });
  fireEvent.click(screen.getByRole("button", { name: "Übernehmen" }));
  await waitFor(() => expect(screen.getByText("Anna")).toBeInTheDocument());
  const put = api.mock.calls.find(([, init]) => init?.method === "PUT");
  expect(JSON.parse(put![1].body)).toEqual({ fine_mode: "rule", fine_rule_id: "r2", fine_fixed_amount: null, fine_split_mode: null });
});

it("hides the settings without finances.manage", async () => {
  api.mockResolvedValue({ ...conflict, state: "on_time", matching_rules: [], can_manage: false });
  render(<TodoFineSection todoId="todo-1" />);
  expect(await screen.findByText("Nicht verspätet.")).toBeInTheDocument();
  expect(screen.queryByLabelText("Busse festlegen")).not.toBeInTheDocument();
});

it("computes amounts like the backend (base + full intervals)", () => {
  expect(ruleAmount(5, 2, 2, 1)).toBe(5);
  expect(ruleAmount(5, 2, 2, 2)).toBe(7);
  expect(ruleAmount(5, 2, 2, 5)).toBe(9);
  expect(ruleAmount(5, 2, 1, 0)).toBe(0);
});
