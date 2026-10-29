import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { EventSummary } from "@/types/api";
import { EventBlockPickerModal } from "./event-block-picker-modal";
import { EventRemoveDialog, eventTagWithout, matchingEventTags } from "./event-remove-dialog";
import { EventSeriesEntry, EventSeriesGroup } from "./event-series-group";

function event(id: string, date: string, overrides: Partial<EventSummary> = {}): EventSummary {
  return {
    id, tenant_id: "t", event_date: date, event_end_date: null, event_category_id: 1, tag: "Training", title: "Hallentraining",
    description: null, participant_count: 0, is_cancelled: false, organizer_ids: null, leadership_ids: null, participant_ids: null,
    spezial1_ids: null, spezial2_ids: null, spezial3_ids: null, location: "Turnhalle Dorf", spezial_text1: null, spezial_text2: null,
    spezial_text3: null, cycle_assignments: [], created_at: "", updated_at: "", ...overrides,
  };
}

const entries: EventSeriesEntry[] = [
  { key: "e1", event: event("e1", "2026-11-18"), label: "", content: <p>Rückblick 18.</p> },
  { key: "e2", event: event("e2", "2026-11-25", { title: "Techniktraining", is_cancelled: true }), label: "", content: <p>Rückblick 25.</p> },
];

function renderGroup(overrides: Partial<Parameters<typeof EventSeriesGroup>[0]> = {}) {
  const handlers = { onChoose: vi.fn(), onEditEvent: vi.fn(), onPostpone: vi.fn(), onRemove: vi.fn() };
  render(<EventSeriesGroup entries={entries} tag="Training" canChoose canEdit {...handlers} {...overrides} />);
  return handlers;
}

describe("EventSeriesGroup", () => {
  it("shows rule, period and counter and one card per event", () => {
    renderGroup();
    expect(screen.getByText("Pro Termin · Tag «Training»")).toBeInTheDocument();
    expect(screen.getByText("18.11.2026 – 25.11.2026 · 2 Termine")).toBeInTheDocument();
    expect(screen.getByText("Rückblick 18.")).toBeInTheDocument();
    expect(screen.getByText("Abgesagt")).toBeInTheDocument();
  });

  it("edits, postpones and removes per event", () => {
    const handlers = renderGroup();
    fireEvent.click(screen.getAllByRole("button", { name: "Vertagen – erscheint im nächsten Protokoll wieder" })[0]);
    expect(handlers.onPostpone).toHaveBeenCalledWith(entries[0]);
    fireEvent.click(screen.getAllByRole("button", { name: "Termin bearbeiten" })[1]);
    expect(handlers.onEditEvent).toHaveBeenCalledWith(entries[1]);
    fireEvent.click(screen.getAllByRole("button", { name: "Entfernen – nie mehr in diesem Punkt anzeigen" })[1]);
    expect(handlers.onRemove).toHaveBeenCalledWith(entries[1]);
    fireEvent.click(screen.getByRole("button", { name: "Termine wählen" }));
    expect(handlers.onChoose).toHaveBeenCalled();
  });

  it("offers choosing only while planning, postponing and removing whenever editable", () => {
    renderGroup({ canChoose: false });
    expect(screen.queryByRole("button", { name: "Termine wählen" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Vertagen – erscheint im nächsten Protokoll wieder" })).toHaveLength(2);
    expect(screen.getAllByRole("button", { name: "Entfernen – nie mehr in diesem Punkt anzeigen" })).toHaveLength(2);
  });

  it("is read-only without any actions", () => {
    renderGroup({ canChoose: false, canEdit: false });
    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });
});

describe("EventRemoveDialog", () => {
  it("finds the event tags matching the series filter and strips them", () => {
    expect(matchingEventTags("Weihnachtsmärt,Anlass", ["weihnacht"])).toEqual(["Weihnachtsmärt"]);
    expect(matchingEventTags("Anlass", ["weihnacht"])).toEqual([]);
    expect(matchingEventTags("Anlass", [])).toEqual([]);
    expect(eventTagWithout("Weihnachtsmärt,Anlass", ["Weihnachtsmärt"])).toBe("Anlass");
    expect(eventTagWithout("Weihnachtsmärt", ["Weihnachtsmärt"])).toBeNull();
  });

  it("removes without tags by default and with the ticked tag on request", () => {
    const onConfirm = vi.fn();
    const { rerender } = render(<EventRemoveDialog open title="Weinachtsmärt" tags={["Weihnachtsmärt"]} busy={false} onClose={vi.fn()} onConfirm={onConfirm} />);
    const dialog = screen.getByRole("dialog", { name: "Termin entfernen" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Entfernen" }));
    expect(onConfirm).toHaveBeenLastCalledWith([]);
    fireEvent.click(within(dialog).getByRole("checkbox", { name: "Tag «Weihnachtsmärt» vom Termin entfernen" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Entfernen" }));
    expect(onConfirm).toHaveBeenLastCalledWith(["Weihnachtsmärt"]);
    rerender(<EventRemoveDialog open title="Weinachtsmärt" tags={[]} busy={false} onClose={vi.fn()} onConfirm={onConfirm} />);
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });
});

describe("EventBlockPickerModal", () => {
  const events = [
    event("past", "2026-11-04"),
    event("e1", "2026-11-18"),
    event("e2", "2026-12-02"),
    event("other", "2026-11-20", { tag: "Sitzung", title: "Vorstandssitzung" }),
  ];

  function renderPicker(overrides: Partial<Parameters<typeof EventBlockPickerModal>[0]> = {}) {
    const handlers = { onToggle: vi.fn(), onRemoveUnknown: vi.fn(), onSelectAllUpcoming: vi.fn(), onSelectNone: vi.fn(), onEditEvent: vi.fn(), onClose: vi.fn() };
    render(
      <EventBlockPickerModal
        open
        tag="Training"
        events={events}
        selectedIds={new Set(["e1"])}
        unknownSelected={[]}
        matchesFilter={(evt) => evt.tag === "Training"}
        protocolDate="2026-11-12"
        loading={false}
        {...handlers}
        {...overrides}
      />
    );
    return handlers;
  }

  it("groups upcoming matching events by month and toggles on click", () => {
    const handlers = renderPicker();
    const dialog = screen.getByRole("dialog", { name: "Termine wählen" });
    expect(within(dialog).getByText("November 2026")).toBeInTheDocument();
    expect(within(dialog).getByText("Dezember 2026")).toBeInTheDocument();
    const cards = within(dialog).getAllByRole("button", { pressed: true });
    expect(cards).toHaveLength(1);
    fireEvent.click(cards[0]);
    expect(handlers.onToggle).toHaveBeenCalledWith("e1", false);
    // Vergangene Termine erst im Reiter «Vergangen», andere Termine aufklappbar
    expect(within(dialog).queryByText("Vorstandssitzung")).not.toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Weitere Termine anzeigen (1)" }));
    expect(within(dialog).getByText("Vorstandssitzung")).toBeInTheDocument();
    expect(within(dialog).getByText("ergibt 1 Block")).toBeInTheDocument();
  });

  it("switches to past events and offers bulk actions", () => {
    const handlers = renderPicker();
    const dialog = screen.getByRole("dialog", { name: "Termine wählen" });
    fireEvent.click(within(dialog).getByRole("tab", { name: "Vergangen" }));
    expect(within(dialog).getAllByRole("button", { pressed: false })).toHaveLength(1);
    fireEvent.click(within(dialog).getByRole("button", { name: "Alle kommenden" }));
    expect(handlers.onSelectAllUpcoming).toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Keine" }));
    expect(handlers.onSelectNone).toHaveBeenCalled();
  });

  it("edits an event without toggling it", () => {
    const handlers = renderPicker();
    const dialog = screen.getByRole("dialog", { name: "Termine wählen" });
    fireEvent.click(within(dialog).getAllByRole("button", { name: "Termin bearbeiten" })[0]);
    expect(handlers.onEditEvent).toHaveBeenCalledWith(events[1]);
    expect(handlers.onToggle).not.toHaveBeenCalled();
  });
});
