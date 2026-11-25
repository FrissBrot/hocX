import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { TaskPackageItem } from "@/types/api";
import { TaskPackageItemModal } from "./task-package-item-modal";
import { dueBeforeCreation, recurrenceLabel } from "./task-package-labels";

const LEAD_LABEL = "Pendenz erstellen: Tage vor dem Termin";

function item(overrides: Partial<TaskPackageItem> = {}): TaskPackageItem {
  return {
    id: "item-1",
    sort_index: 0,
    task: "Programm vorbereiten",
    reference_link: null,
    tags: [],
    responsible: [],
    recurrence: { type: "events", event_tag: "Schar", create_days_before: 14 },
    due_rule: { type: "offset", offset_days: -7 },
    ...overrides,
  };
}

function mount(current: TaskPackageItem | null) {
  const onSave = vi.fn().mockResolvedValue(undefined);
  render(
    <TaskPackageItemModal
      open
      item={current}
      responsibleLists={[]}
      entriesByList={{}}
      participants={[]}
      eventTags={["Schar"]}
      onClose={() => undefined}
      onSave={onSave}
    />
  );
  return onSave;
}

describe("TaskPackageItemModal – Vorlauf pro Termin", () => {
  it("shows the lead field only for «Pro Termin»", () => {
    mount(item({ recurrence: { type: "once" }, due_rule: { type: "none" } }));
    expect(screen.queryByLabelText(LEAD_LABEL)).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Pro Termin"));
    expect(screen.getByLabelText(LEAD_LABEL)).toHaveValue(null);
    fireEvent.click(screen.getByLabelText("Wöchentlich"));
    expect(screen.queryByLabelText(LEAD_LABEL)).not.toBeInTheDocument();
  });

  it("saves the number of days and null when empty", async () => {
    const onSave = mount(item());
    const field = screen.getByLabelText(LEAD_LABEL);
    expect(field).toHaveValue(14);
    fireEvent.change(field, { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: "Speichern" }));
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0][0].recurrence).toEqual({ type: "events", event_tag: "Schar", create_days_before: 10 });

    fireEvent.change(field, { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Speichern" }));
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(2));
    expect(onSave.mock.calls[1][0].recurrence).toEqual({ type: "events", event_tag: "Schar", create_days_before: null });
  });

  it("does not send a lead for other recurrences", async () => {
    const onSave = mount(item());
    fireEvent.click(screen.getByLabelText("Wöchentlich"));
    fireEvent.click(screen.getByRole("button", { name: "Speichern" }));
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0][0].recurrence).toEqual({ type: "weekly", weekday: 0 });
  });

  it("blocks saving for invalid values", () => {
    mount(item());
    const field = screen.getByLabelText(LEAD_LABEL);
    for (const value of ["1.5", "-1", "3651"]) {
      fireEvent.change(field, { target: { value } });
      expect(screen.getByRole("button", { name: "Speichern" })).toBeDisabled();
      expect(field).toHaveAttribute("aria-invalid", "true");
    }
    fireEvent.change(field, { target: { value: "0" } });
    expect(screen.getByRole("button", { name: "Speichern" })).toBeEnabled();
  });

  it("warns (without blocking) when the due date is before the creation date", () => {
    mount(item({ due_rule: { type: "offset", offset_days: -21 } }));
    expect(screen.getByRole("alert")).toHaveTextContent("Die Fälligkeit liegt vor dem Erstelldatum");
    expect(screen.getByRole("button", { name: "Speichern" })).toBeEnabled();
    fireEvent.change(screen.getByLabelText(LEAD_LABEL), { target: { value: "21" } });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("task package lead labels", () => {
  const t = (key: string, values?: Record<string, unknown>) => `${key}${values ? JSON.stringify(values) : ""}`;

  it("adds the lead to the recurrence summary", () => {
    expect(recurrenceLabel({ type: "events", event_tag: "Schar", create_days_before: 14 }, t)).toBe(
      'recurrenceSummary.eventsWithLead{"tag":"Schar","days":14}'
    );
    expect(recurrenceLabel({ type: "events", event_tag: "Schar", create_days_before: null }, t)).toBe('recurrenceSummary.events{"tag":"Schar"}');
    expect(recurrenceLabel({ type: "events", event_tag: "Schar" }, t)).toBe('recurrenceSummary.events{"tag":"Schar"}');
  });

  it("detects a due date before the creation date", () => {
    const events = { type: "events" as const, event_tag: "Schar", create_days_before: 14 };
    expect(dueBeforeCreation(events, { type: "offset", offset_days: -15 })).toBe(true);
    expect(dueBeforeCreation(events, { type: "offset", offset_days: -14 })).toBe(false);
    expect(dueBeforeCreation(events, { type: "offset", offset_days: -7 })).toBe(false);
    expect(dueBeforeCreation(events, { type: "none" })).toBe(false);
    expect(dueBeforeCreation({ type: "events", event_tag: "Schar" }, { type: "offset", offset_days: -30 })).toBe(false);
  });
});
