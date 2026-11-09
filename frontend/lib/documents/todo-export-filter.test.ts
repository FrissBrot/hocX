import { describe, expect, it } from "vitest";

import type { TodoListItem } from "@/types/api";

import {
  dueUntil,
  endOfMonth,
  initialTodoExportFilter,
  isOverdue,
  matchesTodoFilter,
  nextSessionDate,
  todoExportParams,
} from "./todo-export-filter";

const TODAY = "2026-11-09";
const dates = { today: TODAY, nextSession: "2026-11-18" };

function todo(task: string, overrides: Partial<TodoListItem> = {}): TodoListItem {
  return { id: task, task, todo_status_code: "open", resolved_due_date: null, tags: [], assigned_participant_id: null, protocol_id: null, ...overrides } as TodoListItem;
}

// Gleiche Fälle wie backend/tests/documents/test_todo_filters.py
const TODOS = [
  todo("überfällig", { resolved_due_date: "2026-11-05" }),
  todo("heute", { resolved_due_date: TODAY }),
  todo("später", { resolved_due_date: "2026-12-01" }),
  todo("ohne Datum"),
  todo("in Arbeit überfällig", { todo_status_code: "in_progress", resolved_due_date: "2026-10-30" }),
  todo("erledigt überfällig", { todo_status_code: "done", resolved_due_date: "2026-10-01" }),
];

function names(overrides: Partial<ReturnType<typeof initialTodoExportFilter>>) {
  const filter = { ...initialTodoExportFilter(), ...overrides };
  return TODOS.filter((item) => matchesTodoFilter(item, filter, dates)).map((item) => item.task);
}

describe("Pendenzen-Exportfilter", () => {
  it("rechnet überfällig wie der Server", () => {
    expect(isOverdue(TODOS[0], TODAY)).toBe(true);
    expect(isOverdue(TODOS[1], TODAY)).toBe(false);
    expect(isOverdue(TODOS[5], TODAY)).toBe(false);
    expect(names({ due: "overdue" })).toEqual(["überfällig", "in Arbeit überfällig"]);
    expect(names({ status: "all", due: "overdue" })).toEqual(["überfällig", "in Arbeit überfällig"]);
  });

  it("filtert nach Status", () => {
    expect(names({ status: "in_progress" })).toEqual(["in Arbeit überfällig"]);
    expect(names({ status: "done" })).toEqual(["erledigt überfällig"]);
    expect(names({ status: "open" })).toContain("in Arbeit überfällig");
  });

  it("nimmt Pendenzen ohne Fälligkeit nur auf Wunsch mit", () => {
    expect(names({ due: "custom", due_date: TODAY })).toEqual(["überfällig", "heute", "ohne Datum", "in Arbeit überfällig"]);
    expect(names({ due: "custom", due_date: TODAY, include_undated: false })).toEqual(["überfällig", "heute", "in Arbeit überfällig"]);
  });

  it("bestimmt Monatsende und nächste Sitzung", () => {
    expect(endOfMonth("2026-02-10")).toBe("2026-02-28");
    expect(endOfMonth(TODAY)).toBe("2026-11-30");
    const withSession = [todo("a", { due_marker: "next_session", resolved_due_date: "2026-11-18" }), todo("b", { due_marker: "next_session", resolved_due_date: "2026-11-01" })];
    expect(nextSessionDate(withSession, TODAY)).toBe("2026-11-18");
    expect(dueUntil({ ...initialTodoExportFilter(), due: "next_session" }, dates)).toBe("2026-11-18");
  });

  it("schickt dem Server dieselben Filter", () => {
    expect(todoExportParams({ ...initialTodoExportFilter(), due: "overdue", tag: "Vorstand", exclude_ids: ["x"] }, dates)).toEqual({
      status: "open",
      tag: "Vorstand",
      overdue_only: true,
      exclude_ids: ["x"],
    });
    expect(todoExportParams({ ...initialTodoExportFilter(), due: "month", include_undated: false }, dates)).toEqual({
      status: "open",
      due_until: "2026-11-30",
      include_undated: false,
    });
    // Ohne Grenze kein include_undated
    expect(todoExportParams({ ...initialTodoExportFilter(), include_undated: false }, dates)).toEqual({ status: "open" });
  });

  it("übernimmt die Filter der Seite", () => {
    expect(initialTodoExportFilter({ status: "all", tag: "Material" })).toMatchObject({ status: "all", tag: "Material" });
    expect(initialTodoExportFilter({ status: "unbekannt" }).status).toBe("open");
  });
});
