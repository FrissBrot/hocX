import { describe, expect, it } from "vitest";

import type { TodoListItem } from "@/types/api";
import { canToggleTodo } from "@/lib/todo-permissions";
import {
  dueInfo,
  dueShortLabel,
  dueSubLabel,
  groupTodos,
  reassignedIds,
  todoAssignees,
  todoSourceLabel,
} from "./todo-overview-utils";

const TODAY = "2026-11-18";

function todo(overrides: Partial<TodoListItem>): TodoListItem {
  return {
    id: overrides.id ?? "t1",
    protocol_element_block_id: "b1",
    sort_index: 0,
    task: "Aufgabe",
    assigned_user_id: null,
    assigned_participant_id: null,
    assigned_participant_name: null,
    todo_status_id: 1,
    todo_status_code: "open",
    due_date: null,
    due_event_id: null,
    completed_at: null,
    reference_link: null,
    tags: [],
    created_by: null,
    created_at: "2026-11-01T00:00:00Z",
    updated_at: "2026-11-01T00:00:00Z",
    closed_in_protocol_id: null,
    protocol_id: null,
    protocol_number: null,
    protocol_date: null,
    protocol_title: null,
    protocol_status: null,
    block_title: null,
    submission_assignment_id: null,
    element_ref: null,
    ...overrides,
  };
}

// Gibt Schlüssel und Werte zurück, damit die Tests ohne Übersetzungsdateien auskommen
const t = (key: string, values?: Record<string, string | number | Date>) =>
  values ? `${key}:${Object.entries(values).map(([k, v]) => `${k}=${String(v)}`).join(",")}` : key;

describe("dueInfo / groupTodos", () => {
  it("ordnet nach Fälligkeit in der festen Gruppenreihenfolge", () => {
    const items = [
      todo({ id: "later", resolved_due_date: "2026-12-31" }),
      todo({ id: "overdue", resolved_due_date: "2026-11-10" }),
      todo({ id: "soon", resolved_due_date: "2026-11-22" }),
      todo({ id: "session", due_marker: "next_session", resolved_due_date: "2026-11-20" }),
      todo({ id: "submission", submission_assignment_id: "s1" }),
      todo({ id: "none" }),
      todo({ id: "done", todo_status_code: "done", resolved_due_date: "2026-11-01" }),
      todo({ id: "soon-first", resolved_due_date: "2026-11-19" }),
    ];
    const groups = groupTodos(items, TODAY);
    expect(groups.map((group) => group.key)).toEqual(["overdue", "soon", "later", "session", "submission", "none", "done"]);
    expect(groups[1].items.map((item) => item.id)).toEqual(["soon-first", "soon"]);
  });

  it("Grenze «Nächste 14 Tage» und Ton", () => {
    expect(dueInfo(todo({ resolved_due_date: "2026-12-02" }), TODAY)).toMatchObject({ group: "soon", tone: "soon", days: 14 });
    expect(dueInfo(todo({ resolved_due_date: "2026-12-03" }), TODAY)).toMatchObject({ group: "later", tone: "normal" });
    expect(dueInfo(todo({ resolved_due_date: "2026-11-17" }), TODAY)).toMatchObject({ group: "overdue", tone: "overdue", days: -1 });
  });

  it("Abgabe mit eigenem Datum bleibt in der Datumsgruppe", () => {
    expect(dueInfo(todo({ submission_assignment_id: "s1", resolved_due_date: "2026-11-25" }), TODAY).group).toBe("soon");
  });

  it("Texte der Fälligkeit", () => {
    expect(dueSubLabel(dueInfo(todo({ resolved_due_date: "2026-11-15" }), TODAY), t)).toBe("v2.overdueSinceDays:count=3");
    expect(dueSubLabel(dueInfo(todo({ resolved_due_date: "2026-11-22" }), TODAY), t)).toBe("v2.inDays:count=4");
    expect(dueSubLabel(dueInfo(todo({ resolved_due_date: "2026-12-30" }), TODAY), t)).toBe("v2.inWeeks:count=6");
    expect(dueSubLabel(dueInfo(todo({ due_marker: "next_session" }), TODAY), t)).toBe("v2.dateOpen");
    expect(dueShortLabel(dueInfo(todo({ resolved_due_date: "2026-11-22" }), TODAY), t)).toBe("v2.boardDueSoon:date=22.11.,count=4");
  });
});

describe("Zuweisung", () => {
  it("liest Mehrfach- und Einzelzuweisung", () => {
    expect(todoAssignees(todo({ assigned_participant_ids: ["a", "b"], assigned_participant_names: ["Anna", "Ben"] }))).toEqual([
      { id: "a", name: "Anna" },
      { id: "b", name: "Ben" },
    ]);
    expect(todoAssignees(todo({ assigned_participant_id: "a", assigned_participant_name: "Anna" }))).toEqual([{ id: "a", name: "Anna" }]);
    expect(todoAssignees(todo({}))).toEqual([]);
  });

  it("Board: Ausgangsperson raus, Zielperson rein, «Nicht zugewiesen» leert", () => {
    expect(reassignedIds(["a", "b"], "a", "c")).toEqual(["b", "c"]);
    expect(reassignedIds(["a", "b"], "a", "b")).toEqual(["b"]);
    expect(reassignedIds([], null, "c")).toEqual(["c"]);
    expect(reassignedIds(["a", "b"], "a", null)).toEqual([]);
  });
});

describe("Quelle", () => {
  it("Protokoll, Abgabe, manuell", () => {
    expect(todoSourceLabel(todo({ protocol_id: "p", protocol_title: "Hock 14", protocol_date: "2026-11-03" }), t)).toBe("v2.sourceProtocol:name=Hock 14,date=03.11.2026");
    expect(todoSourceLabel(todo({ submission_assignment_id: "s", submission_title: "Jahresbericht" }), t)).toBe("v2.sourceSubmission:title=Jahresbericht");
    expect(todoSourceLabel(todo({}), t)).toBe("manuallyCreated");
  });
});

describe("canToggleTodo", () => {
  it("heute an meetings.edit gebunden", () => {
    const base = { current_tenant: null, user: null };
    expect(canToggleTodo({ ...base, permissions: ["meetings.edit"] }, todo({}))).toBe(true);
    expect(canToggleTodo({ ...base, permissions: ["meetings.read"] }, todo({}))).toBe(false);
    expect(canToggleTodo(null, todo({}))).toBe(false);
  });
});
