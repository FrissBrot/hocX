import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { EventCalendarModal } from "./event-calendar-modal";
import { EventSummary } from "@/types/api";

function makeEvent(overrides: Partial<EventSummary> = {}): EventSummary {
  return {
    id: "event-1",
    tenant_id: "tenant-1",
    event_date: "2026-11-08",
    event_end_date: null,
    event_category_id: 1,
    tag: "Hock",
    title: "Hock November",
    description: null,
    participant_count: 0,
    is_cancelled: false,
    organizer_ids: null,
    leadership_ids: null,
    participant_ids: null,
    spezial1_ids: null,
    spezial2_ids: null,
    spezial3_ids: null,
    location: null,
    spezial_text1: null,
    spezial_text2: null,
    spezial_text3: null,
    cycle_assignments: [],
    created_at: "2026-10-01T10:00:00Z",
    updated_at: "2026-10-01T10:00:00Z",
    ...overrides,
  };
}

describe("EventCalendarModal im Auswahlmodus", () => {
  it("startet beim aktuellen Wert, zeigt die Termine und übernimmt einen angeklickten Tag", () => {
    const onPick = vi.fn();
    const onClose = vi.fn();
    render(
      <EventCalendarModal
        open
        onClose={onClose}
        events={[makeEvent()]}
        todayIso="2026-10-05"
        tagColor={() => "var(--primary)"}
        pick={{ value: "2026-11-08", title: "Datum für den nächsten Hock", hint: "Klicke auf einen Tag", onPick }}
      />
    );

    // Kalender öffnet im Monat des gewählten Datums, nicht beim heutigen Tag.
    expect(screen.getByText("Hock November")).toBeTruthy();
    expect(screen.getByText("Klicke auf einen Tag")).toBeTruthy();
    // Keine Seitenleiste mit „Termin anlegen" im Auswahlmodus.
    expect(document.querySelector(".event-cal-side")).toBeNull();

    const cells = screen.getAllByRole("gridcell");
    const selectedIndex = cells.findIndex((cell) => cell.getAttribute("aria-selected") === "true");
    expect(selectedIndex).toBeGreaterThanOrEqual(0);
    fireEvent.click(cells[selectedIndex + 1]);

    expect(onPick).toHaveBeenCalledWith("2026-11-09");
    expect(onClose).toHaveBeenCalled();
  });
});
