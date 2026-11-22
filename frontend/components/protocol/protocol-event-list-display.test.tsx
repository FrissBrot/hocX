import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  EventDateTile,
  EventListToolbar,
  EventSessionSeparator,
  EventTagLine,
  eventTagColor,
  eventTimeline,
} from "./protocol-event-list-display";

// Terminliste im Protokoll: Grenze vergangen/kommend = Sitzungsdatum (Enddatum zählt),
// Trennzeile an der Grenze, Umschalter Alle/Kommend nur mit vergangenen Terminen.

const rows = [
  { event_date: "2026-11-01", event_end_date: null },
  { event_date: "2026-11-18", event_end_date: "2026-11-22" },
  { event_date: "2026-11-22", event_end_date: null },
  { event_date: "2026-12-05", event_end_date: null },
];

describe("eventTimeline", () => {
  it("trennt aufsteigend vor dem ersten kommenden Termin, mehrtägige zählen bis zum Enddatum", () => {
    const timeline = eventTimeline(rows, "2026-11-22");
    expect(timeline.past).toEqual([true, false, false, false]);
    expect(timeline.pastCount).toBe(1);
    expect(timeline.upcomingCount).toBe(3);
    expect(timeline.boundaryIndex).toBe(1);
    expect(timeline.boundaryStartsUpcoming).toBe(true);
    expect(timeline.firstUpcomingIndex).toBe(1);
  });

  it("trennt absteigend vor dem ersten vergangenen Termin", () => {
    const timeline = eventTimeline([...rows].reverse(), "2026-11-22");
    expect(timeline.boundaryIndex).toBe(3);
    expect(timeline.boundaryStartsUpcoming).toBe(false);
    expect(timeline.firstUpcomingIndex).toBe(0);
  });

  it("hat ohne Sitzungsdatum oder ohne Wechsel keine Trennzeile", () => {
    expect(eventTimeline(rows, null).boundaryIndex).toBe(-1);
    expect(eventTimeline(rows, null).pastCount).toBe(0);
    expect(eventTimeline(rows.slice(1), "2026-11-22").boundaryIndex).toBe(-1);
  });
});

describe("EventListToolbar", () => {
  it("zeigt die Zusammenfassung und den Umschalter nur mit vergangenen Terminen", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <EventListToolbar timeline={eventTimeline(rows, "2026-11-22")} upcomingOnly={false} onChangeUpcomingOnly={onChange} />
    );
    expect(screen.getByText("3 kommend · 1 vergangen")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Alle/ })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(screen.getByRole("tab", { name: /Kommend/ }));
    expect(onChange).toHaveBeenCalledWith(true);

    rerender(<EventListToolbar timeline={eventTimeline(rows.slice(1), "2026-11-22")} upcomingOnly={false} onChangeUpcomingOnly={onChange} />);
    expect(screen.getByText("3 kommend · 0 vergangen")).toBeInTheDocument();
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
  });

  it("wechselt per Pfeiltaste auf «Kommend» (Tastaturvertrag FilterTabs)", () => {
    const onChange = vi.fn();
    render(<EventListToolbar timeline={eventTimeline(rows, "2026-11-22")} upcomingOnly={false} onChangeUpcomingOnly={onChange} />);
    const all = screen.getByRole("tab", { name: /Alle/ });
    all.focus();
    fireEvent.keyDown(all, { key: "ArrowRight" });
    expect(onChange).toHaveBeenCalledWith(true);
  });
});

describe("EventSessionSeparator", () => {
  function renderSeparator(startsUpcoming: boolean, protocolDate: string | null) {
    return render(
      <table>
        <tbody>
          <EventSessionSeparator colSpan={4} protocolDate={protocolDate} startsUpcoming={startsUpcoming} />
        </tbody>
      </table>
    );
  }

  it("beschriftet die Grenze mit dem Sitzungsdatum", () => {
    renderSeparator(true, "2026-11-22");
    expect(screen.getByText("Ab Sitzung vom 22.11.2026").closest("td")).toHaveAttribute("colspan", "4");
  });

  it("beschriftet absteigende Listen als «Vor der Sitzung»", () => {
    renderSeparator(false, "2026-11-22");
    expect(screen.getByText("Vor der Sitzung vom 22.11.2026")).toBeInTheDocument();
  });
});

describe("Kachel und Tags", () => {
  it("zeigt Monat, Tag und Wochentag, das ganze Datum für Screenreader und ein Enddatum", () => {
    render(<EventDateTile date="2026-12-05" endDate="2026-12-06" color="#2563eb" />);
    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("bis 06.12.2026")).toBeInTheDocument();
    const tile = document.querySelector(".protocol-event-tile") as HTMLElement;
    expect(tile.style.getPropertyValue("--tag-color")).toBe("#2563eb");
    expect(document.querySelector(".visually-hidden")?.textContent).toContain("05.12.2026");
  });

  it("nimmt die erste konfigurierte Tag-Farbe und zeigt jeden Tag mit Punkt", () => {
    const tagConfig = { Lager: { color: "#16a34a" }, Probe: {} };
    expect(eventTagColor("Probe, Lager", tagConfig)).toBe("#16a34a");
    expect(eventTagColor("Probe", tagConfig)).toBeNull();
    render(<EventTagLine tag="Probe, Lager" tagConfig={tagConfig} />);
    expect(screen.getByText("Probe")).toBeInTheDocument();
    expect(screen.getByText("Lager")).toBeInTheDocument();
    expect(document.querySelectorAll(".protocol-event-tag-dot")).toHaveLength(2);
  });
});
