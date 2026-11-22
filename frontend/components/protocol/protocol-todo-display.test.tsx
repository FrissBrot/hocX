import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/contexts/toast-context", () => ({ useToast: () => vi.fn() }));

import type { ParticipantSummary, ProtocolSummary, ProtocolTodo } from "@/types/api";
import { TodoMiniMenu } from "./protocol-editor-shared";
import { SessionTodosSection } from "./session-todos-section";
import { TodoProgress, personInitials, protocolTodoDue, protocolTodoDueTone, todoDueBadgeLabel, todoDueTriggerClass } from "./protocol-todo-display";

// Pendenzen im Protokoll: Fälligkeit farbig nach derselben Regel wie die Übersicht (dueInfo,
// 14 Tage), erledigte durchgestrichen an ihrer Position, Fortschritt und Initialen.

const today = "2026-11-22";
const base = { due_date: null, due_marker: null, resolved_due_date: null, todo_status_code: "open", submission_assignment_id: null };

describe("protocolTodoDueTone", () => {
  it("rot überfällig, gelb innerhalb von 14 Tagen, sonst neutral", () => {
    expect(protocolTodoDueTone({ ...base, due_date: "2026-11-21" }, today)).toBe("overdue");
    expect(protocolTodoDueTone({ ...base, due_date: "2026-11-22" }, today)).toBe("soon");
    expect(protocolTodoDueTone({ ...base, resolved_due_date: "2026-12-06" }, today)).toBe("soon");
    expect(protocolTodoDueTone({ ...base, resolved_due_date: "2026-12-07" }, today)).toBe("normal");
    expect(protocolTodoDueTone(base, today)).toBe("normal");
  });

  it("erledigte Pendenzen sind nie rot oder gelb", () => {
    const tone = protocolTodoDueTone({ ...base, due_date: "2026-01-01", todo_status_code: "done" }, today);
    expect(tone).toBe("done");
    expect(todoDueTriggerClass(tone)).toBe("todo-due-trigger");
  });
});

describe("todoDueBadgeLabel", () => {
  const t = (key: string, values?: Record<string, string | number>) =>
    key === "todoDueOverdueBadge" ? `Überfällig · ${values?.date}` : key === "todoDueToday" ? "Heute" : `In ${values?.count} Tagen`;
  it("zeigt «Überfällig · TT.MM.», «Heute», «In N Tagen», sonst den bisherigen Text", () => {
    expect(todoDueBadgeLabel(protocolTodoDue({ ...base, due_date: "2026-11-20" }, today), "20.11.2026", t)).toBe("Überfällig · 20.11.");
    expect(todoDueBadgeLabel(protocolTodoDue({ ...base, due_date: "2026-11-22" }, today), "22.11.2026", t)).toBe("Heute");
    expect(todoDueBadgeLabel(protocolTodoDue({ ...base, due_date: "2026-11-27" }, today), "27.11.2026", t)).toBe("In 5 Tagen");
    expect(todoDueBadgeLabel(protocolTodoDue({ ...base, due_date: "2027-01-10" }, today), "10.01.2027", t)).toBe("10.01.2027");
    expect(todoDueBadgeLabel(protocolTodoDue(base, today), "Kein Enddatum", t)).toBe("Kein Enddatum");
    expect(todoDueBadgeLabel(protocolTodoDue({ ...base, due_date: "2026-11-01", todo_status_code: "done" }, today), "01.11.2026", t)).toBe("01.11.2026");
  });
});

describe("TodoMiniMenu als Fälligkeits-Badge", () => {
  it("trägt die Farbklasse und öffnet weiter das Fälligkeitsmenü", () => {
    render(
      <TodoMiniMenu label="21.11.2026" triggerClassName={todoDueTriggerClass("overdue")} leading={<span>überfällig</span>}>
        {() => <button type="button">Kein Enddatum</button>}
      </TodoMiniMenu>
    );
    const trigger = screen.getByRole("button", { name: /überfällig.*21\.11\.2026/ });
    expect(trigger).toHaveClass("mini-menu-trigger", "todo-due-trigger-overdue");
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: "Kein Enddatum" })).toBeInTheDocument();
  });

  it("setzt den Fokus beim Öffnen ins Menü und gibt ihn mit Escape an das Badge zurück", () => {
    render(
      <TodoMiniMenu label="Kein Enddatum">
        {() => <button type="button">Kein Enddatum wählen</button>}
      </TodoMiniMenu>
    );
    const trigger = screen.getByRole("button", { name: /Kein Enddatum/ });
    trigger.focus();
    fireEvent.click(trigger);
    expect(screen.getByRole("button", { name: "Kein Enddatum wählen" })).toHaveFocus();
    fireEvent.keyDown(screen.getByRole("button", { name: "Kein Enddatum wählen" }), { key: "Escape" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).toHaveFocus();
  });
});

describe("Fortschritt und Initialen", () => {
  it("zeigt «X von Y erledigt» mit Prozent", () => {
    render(<TodoProgress done={1} total={3} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-label", "1 von 3 erledigt");
    expect(screen.getByText("2 offen · 1 erledigt")).toBeInTheDocument();
    expect(screen.getByText("33 %")).toBeInTheDocument();
  });

  it("bildet Initialen aus höchstens zwei Namensteilen", () => {
    expect(personInitials("anna maria muster")).toBe("AM");
    expect(personInitials(null)).toBe("");
  });
});

describe("SessionTodosSection", () => {
  const anna = { id: "pa-1", display_name: "Anna Muster", joined_at: null, left_at: null } as unknown as ParticipantSummary;
  const todo = (id: string, task: string, status: string, due?: string) => ({
    id, task, todo_status_code: status, protocol_element_block_id: "b-1", assigned_participant_id: "pa-1",
    assigned_participant_name: "Anna Muster", due_date: due ?? null, due_marker: null, due_event_id: null,
    resolved_due_date: null, tags: [],
  }) as unknown as ProtocolTodo;

  it("streicht erledigte durch, lässt sie an ihrer Stelle und färbt überfällige Fälligkeit", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 10, 22, 12));
    render(
      <SessionTodosSection
        sectionTag="Vorstand"
        todos={[todo("t-1", "Offen eins", "open", "2026-11-20"), todo("t-2", "Erledigt", "done"), todo("t-3", "Offen zwei", "open")]}
        isReadOnly={false}
        participants={[anna]}
        dueEvents={[]}
        protocol={{ id: "p-1", protocol_date: "2026-11-22" } as unknown as ProtocolSummary}
        onUpdate={vi.fn()}
        onDelete={vi.fn()}
        onPendingUpdate={vi.fn()}
        onPendingDone={vi.fn()}
      />
    );
    const cards = Array.from(document.querySelectorAll("article.todo-card"));
    expect(cards.map((card) => card.classList.contains("todo-card-strike"))).toEqual([false, true, false]);
    expect(screen.getAllByText("AM").length).toBeGreaterThan(0);
    const overdue = document.querySelector(".todo-due-trigger-overdue");
    expect(overdue).not.toBeNull();
    expect(overdue?.textContent).toContain("überfällig");
    vi.useRealTimers();
  });
});
