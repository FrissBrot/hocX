import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { TaskPackage } from "@/types/api";
const api = vi.hoisted(() => vi.fn());
const toast = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/client", () => ({ browserApiFetch: api }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => toast }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => vi.fn().mockResolvedValue(true) }));
import { TaskPackageManager } from "./task-package-manager";
import { currentCycleYear, dueRuleLabel } from "./task-package-labels";

const pkg: TaskPackage = {
  id: "pkg-1",
  name: "Sommerlager",
  description: null,
  is_active: true,
  cycles: [{ id: "pc-1", cycle_config_id: "cy-1", cycle_config_name: "Scharjahr", start_cycle_year: 2026, current_cycle_year: 2026, current_cycle_label: "2026/2027" }],
  items: [
    {
      id: "item-1",
      sort_index: 0,
      task: "Lagerplatz reservieren",
      reference_link: null,
      tags: [],
      responsible: [{ list_definition_id: "list-1", list_entry_id: "entry-1" }],
      recurrence: { type: "once" },
      due_rule: { type: "fixed", day: 31, month: 3 },
    },
  ],
  open_todo_count: 1,
  todo_count: 1,
  created_at: "2026-10-12T00:00:00Z",
  updated_at: "2026-10-12T00:00:00Z",
};

function mount() {
  render(
    <TaskPackageManager
      initialPackages={[pkg]}
      cycleConfigs={[{ id: "cy-1", tenant_id: "t", name: "Scharjahr", reset_month: 7, reset_day: 31 }]}
      responsibleLists={[
        {
          id: "list-1", tenant_id: "t", name: "Ämtliliste", description: null, column_one_title: "Ämtli", column_one_value_type: "text",
          column_two_title: "Personen", column_two_value_type: "participants", is_active: true, content_version: 1, created_at: "", updated_at: "",
        },
      ]}
      entriesByList={{
        "list-1": [{ id: "entry-1", list_definition_id: "list-1", sort_index: 0, column_one_value: { text_value: "Lagerleitung" }, column_two_value: { participant_ids: ["p-1", "p-2"] }, created_at: "", updated_at: "" }],
      }}
      participants={[
        { id: "p-1", display_name: "Anna" },
        { id: "p-2", display_name: "Ben" },
      ] as never}
      eventTags={[]}
    />
  );
}

beforeEach(() => vi.clearAllMocks());

describe("TaskPackageManager", () => {
  it("shows the aemtli with its current people", () => {
    mount();
    expect(screen.getByText("Lagerleitung (Anna, Ben)")).toBeInTheDocument();
  });

  it("asks what happens to existing tasks before deleting a package", async () => {
    api.mockResolvedValue({ deleted: 0, kept: 1 });
    mount();
    fireEvent.click(screen.getByRole("button", { name: /Aktionen für Sommerlager/ }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Löschen" }));
    fireEvent.click(await screen.findByLabelText(/Keine Aufgaben löschen/));
    fireEvent.click(screen.getByRole("button", { name: "Paket löschen" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/task-packages/pkg-1?todos=none", { method: "DELETE" }));
    await waitFor(() => expect(screen.queryByText("Lagerplatz reservieren")).not.toBeInTheDocument());
  });
});

describe("task package labels", () => {
  it("computes the current cycle like the backend", () => {
    expect(currentCycleYear({ reset_month: 7, reset_day: 31 }, new Date(2026, 6, 31))).toBe(2025);
    expect(currentCycleYear({ reset_month: 7, reset_day: 31 }, new Date(2026, 7, 1))).toBe(2026);
    expect(currentCycleYear({ reset_month: 12, reset_day: 31 }, new Date(2026, 4, 1))).toBe(2026);
    expect(currentCycleYear({ reset_month: 2, reset_day: 30 }, new Date(2026, 2, 1))).toBe(2026);
  });

  it("describes relative due dates", () => {
    const t = (key: string, values?: Record<string, unknown>) => `${key}${values ? JSON.stringify(values) : ""}`;
    expect(dueRuleLabel({ type: "offset", offset_days: -14 }, { type: "events", event_tag: "Lager" }, t)).toBe(
      'dueSummary.before{"days":14,"anchor":"anchor.event"}'
    );
  });
});
