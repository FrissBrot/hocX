import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ParticipantSummary } from "@/types/api";
import { AttendanceBoard, nextAttendanceStatus } from "./attendance-board";

function person(id: string, name: string): ParticipantSummary {
  return {
    id, tenant_id: "t", display_name: name, first_name: null, last_name: null, email: null, is_active: true,
    joined_at: null, left_at: null, created_at: "", updated_at: "", exclude_from_attendance: false,
  } as ParticipantSummary;
}

const people = [person("p1", "Anna Berger"), person("p2", "Luca Meier"), person("p3", "Sara Keller"), person("p4", "Marco Rossi")];

function renderBoard(overrides: Partial<Parameters<typeof AttendanceBoard>[0]> = {}) {
  const handlers = { onChange: vi.fn(), onMarkOpenPresent: vi.fn() };
  render(
    <AttendanceBoard
      participants={people}
      statusById={new Map([["p1", "present"], ["p2", "late"], ["p4", "absent"]])}
      editable
      fineAmountById={new Map([["p4", 20]])}
      {...handlers}
      {...overrides}
    />
  );
  return handlers;
}

describe("AttendanceBoard", () => {
  it("shows summary, counts per status and one card per person", () => {
    renderBoard();
    expect(screen.getByText("4 Teilnehmende · 2 Abweichungen · 1 offen")).toBeInTheDocument();
    const filters = screen.getByRole("group", { name: "Nach Status filtern" });
    expect(within(filters).getByRole("button", { name: /Alle\s*4/ })).toBeInTheDocument();
    expect(within(filters).getByRole("button", { name: /Offen\s*1/ })).toBeInTheDocument();
    expect(within(filters).getByRole("button", { name: /Unentschuldigt\s*1/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Marco Rossi/ })).toHaveTextContent("CHF 20");
  });

  it("filters by status tile and by search", () => {
    renderBoard();
    fireEvent.click(within(screen.getByRole("group", { name: "Nach Status filtern" })).getByRole("button", { name: /Verspaetet/ }));
    expect(screen.getByRole("button", { name: /Luca Meier/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Anna Berger/ })).not.toBeInTheDocument();
    fireEvent.click(within(screen.getByRole("group", { name: "Nach Status filtern" })).getByRole("button", { name: /Alle/ }));
    fireEvent.change(screen.getByRole("textbox", { name: "Person suchen …" }), { target: { value: "xyz" } });
    expect(screen.getByText("Keine Person gefunden für «xyz»")).toBeInTheDocument();
  });

  it("cycles the status on click", () => {
    const handlers = renderBoard();
    fireEvent.click(screen.getByRole("button", { name: /Sara Keller/ }));
    expect(handlers.onChange).toHaveBeenLastCalledWith(people[2], "present");
    fireEvent.click(screen.getByRole("button", { name: /Luca Meier/ }));
    expect(handlers.onChange).toHaveBeenLastCalledWith(people[1], "excused");
    fireEvent.click(screen.getByRole("button", { name: /Marco Rossi/ }));
    expect(handlers.onChange).toHaveBeenLastCalledWith(people[3], "present");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("opens the menu on long press without cycling", () => {
    vi.useFakeTimers();
    try {
      const handlers = renderBoard();
      const card = screen.getByRole("button", { name: /Sara Keller/ });
      fireEvent.pointerDown(card, { button: 0 });
      act(() => vi.advanceTimersByTime(500));
      fireEvent.pointerUp(card);
      fireEvent.click(card);
      expect(handlers.onChange).not.toHaveBeenCalled();
      fireEvent.click(screen.getByRole("menuitem", { name: /Entschuldigt/ }));
      expect(handlers.onChange).toHaveBeenLastCalledWith(people[2], "excused");
    } finally {
      vi.useRealTimers();
    }
  });

  it("sets a status with number keys on the focused or hovered person", () => {
    const handlers = renderBoard();
    fireEvent.focus(screen.getByRole("button", { name: /Luca Meier/ }));
    fireEvent.keyDown(window, { key: "3" });
    expect(handlers.onChange).toHaveBeenLastCalledWith(people[1], "excused");
    fireEvent.mouseEnter(screen.getByRole("button", { name: /Anna Berger/ }));
    fireEvent.keyDown(window, { key: "4" });
    expect(handlers.onChange).toHaveBeenLastCalledWith(people[0], "absent");
    expect(nextAttendanceStatus("open")).toBe("present");
    expect(nextAttendanceStatus("absent")).toBe("present");
  });

  it("opens the menu of the only search hit with Enter", () => {
    renderBoard();
    const search = screen.getByRole("textbox", { name: "Person suchen …" });
    fireEvent.change(search, { target: { value: "sara" } });
    fireEvent.keyDown(search, { key: "Enter" });
    expect(screen.getByRole("menu")).toBeInTheDocument();
  });

  it("marks only open people present", () => {
    const handlers = renderBoard();
    fireEvent.click(screen.getByRole("button", { name: "Übrige auf anwesend" }));
    expect(handlers.onMarkOpenPresent).toHaveBeenCalledWith([people[2]]);
  });

  it("is read-only without actions", () => {
    const handlers = renderBoard({ editable: false });
    expect(screen.queryByRole("button", { name: "Übrige auf anwesend" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Anna Berger/ })).toBeDisabled();
    fireEvent.mouseEnter(screen.getByRole("button", { name: /Anna Berger/ }));
    fireEvent.keyDown(window, { key: "2" });
    expect(handlers.onChange).not.toHaveBeenCalled();
  });
});
