import { afterEach, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { StructuredListTable } from "./structured-list-table";
import { ParticipantSummary, StructuredListDefinition, StructuredListEntry } from "@/types/api";

afterEach(() => vi.useRealTimers());

it("zeigt eingefrorene Teilnehmernamen auch ohne aktuelle Katalogeinträge", () => {
  const definition = { id: "list", name: "Sponsoring", column_one_title: "Sponsor", column_one_value_type: "text",
    column_two_title: "Verantwortlich", column_two_value_type: "participants" } as StructuredListDefinition;
  const entries = [{ id: "entry", sort_index: 0, column_one_value: { text_value: "Karo" },
    column_two_value: { participant_ids: ["old-1", "old-2"], participant_names: ["Damals Anna", "Damals Beat"] } }] as unknown as StructuredListEntry[];
  render(<StructuredListTable definition={definition} entries={entries} availableParticipants={[]} availableEvents={[]}
    editable={false} onCreateEntry={vi.fn()} onUpdateEntry={vi.fn()} onDeleteEntry={vi.fn()} />);
  expect(screen.getByText("Damals Anna, Damals Beat")).toBeInTheDocument();
});

it("zeigt einen historischen Einzelverantwortlichen trotz späterem Austritt", () => {
  const definition = { id: "list", name: "Sponsoring", column_one_title: "Sponsor", column_one_value_type: "text",
    column_two_title: "Verantwortlich", column_two_value_type: "participant" } as StructuredListDefinition;
  const entries = [{ id: "entry", sort_index: 0, column_one_value: { text_value: "Karo" },
    column_two_value: { participant_id: "old", participant_name: "Damals Anna" } }] as unknown as StructuredListEntry[];
  render(<StructuredListTable definition={definition} entries={entries} availableParticipants={[]} availableEvents={[]}
    editable={false} onCreateEntry={vi.fn()} onUpdateEntry={vi.fn()} onDeleteEntry={vi.fn()} />);
  expect(screen.getByText("Damals Anna")).toBeInTheDocument();
});

it("markiert in aktuellen Listen nur bereits ausgetretene Verknüpfungen orange", () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date(2026, 9, 4, 12));
  const definition = { id: "list", name: "Sponsoring", column_one_title: "Sponsor", column_one_value_type: "text",
    column_two_title: "Verantwortlich", column_two_value_type: "participants" } as StructuredListDefinition;
  const participants = [
    { id: "old", display_name: "Ausgetreten", left_at: "2026-08-15" },
    { id: "today", display_name: "Austritt heute", left_at: "2026-10-04" },
    { id: "active", display_name: "Aktiv", left_at: null },
  ] as unknown as ParticipantSummary[];
  const entries = [{ id: "entry", sort_index: 0, column_one_value: { text_value: "Karo" },
    column_two_value: { participant_ids: participants.map((p) => p.id) } }] as unknown as StructuredListEntry[];
  const props = { definition, entries, availableParticipants: participants, availableEvents: [], editable: false,
    onCreateEntry: vi.fn(), onUpdateEntry: vi.fn(), onDeleteEntry: vi.fn() };
  const { rerender } = render(<StructuredListTable {...props} highlightDepartedParticipants />);
  expect(screen.getByText("Ausgetreten").closest(".badge-warning")).not.toBeNull();
  expect(screen.getByText("Ausgetreten")).toHaveAttribute("title", "Ausgetreten am 15.08.2026");
  expect(screen.getByText(/Austritt heute/).closest(".badge-warning")).toBeNull();
  rerender(<StructuredListTable {...props} highlightDepartedParticipants={false} />);
  expect(document.querySelector(".badge-warning")).toBeNull();
  vi.useRealTimers();
});

it("markiert die bestehende Einzelauswahl orange und erhält ihre Verknüpfung", () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date(2026, 9, 4, 12));
  const definition = { id: "list", name: "Sponsoring", column_one_title: "Sponsor", column_one_value_type: "text",
    column_two_title: "Verantwortlich", column_two_value_type: "participant" } as StructuredListDefinition;
  const entries = [{ id: "entry", sort_index: 0, column_one_value: { text_value: "Karo" },
    column_two_value: { participant_id: "old" } }] as unknown as StructuredListEntry[];
  render(<StructuredListTable definition={definition} entries={entries}
    availableParticipants={[{ id: "old", display_name: "Ausgetreten", left_at: "2026-08-15" }] as unknown as ParticipantSummary[]}
    availableEvents={[]} highlightDepartedParticipants allowCreate={false}
    onCreateEntry={vi.fn()} onUpdateEntry={vi.fn()} onDeleteEntry={vi.fn()} />);
  const trigger = screen.getByRole("button", { name: /Ausgetreten/ });
  expect(trigger.closest(".structured-list-departed")).not.toBeNull();
  expect(trigger).toHaveAttribute("title", "Ausgetreten am 15.08.2026");
  vi.useRealTimers();
});


it("entfernt einen Teilnehmerchip und speichert nur die verbleibende Zuordnung", async () => {
  vi.useFakeTimers();
  const definition = { id: "list", name: "Gruppen", column_one_title: "Gruppe", column_one_value_type: "text",
    column_two_title: "Leitende", column_two_value_type: "participants" } as StructuredListDefinition;
  const entries = [{ id: "entry", sort_index: 0, column_one_value: { text_value: "Wölfe" },
    column_two_value: { participant_ids: ["anna", "beat"] } }] as unknown as StructuredListEntry[];
  const onUpdateEntry = vi.fn().mockResolvedValue(true);
  render(<StructuredListTable definition={definition} entries={entries} masterList
    availableParticipants={[{ id: "anna", display_name: "Anna" }, { id: "beat", display_name: "Beat" }] as ParticipantSummary[]}
    availableEvents={[]} onCreateEntry={vi.fn()} onUpdateEntry={onUpdateEntry} onDeleteEntry={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Anna entfernen" }));
  expect(screen.queryByRole("button", { name: "Anna entfernen" })).not.toBeInTheDocument();
  await act(async () => { await vi.advanceTimersByTimeAsync(500); });
  expect(onUpdateEntry).toHaveBeenCalledWith("entry", { column_two_value: { participant_ids: ["beat"] } });
});

it("fügt bei aktiver Suche hinter dem vollständigen Datenbestand hinzu", async () => {
  vi.useFakeTimers();
  const definition = { id: "list", name: "Gruppen", column_one_title: "Gruppe", column_one_value_type: "text",
    column_two_title: "Notiz", column_two_value_type: "text" } as StructuredListDefinition;
  const entries = [{ id: "hidden", sort_index: 9, column_one_value: { text_value: "Versteckt" }, column_two_value: { text_value: "" } }] as unknown as StructuredListEntry[];
  const onCreateEntry = vi.fn().mockResolvedValue(true);
  render(<StructuredListTable definition={definition} entries={entries} masterList visibleEntryIds={[]}
    availableParticipants={[]} availableEvents={[]} onCreateEntry={onCreateEntry} onUpdateEntry={vi.fn()} onDeleteEntry={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "+ Eintrag hinzufügen" }));
  fireEvent.change(screen.getAllByPlaceholderText("Wert")[0], { target: { value: "Neu" } });
  await act(async () => { await vi.advanceTimersByTimeAsync(500); });
  expect(onCreateEntry).toHaveBeenCalledWith(expect.objectContaining({ sort_index: 19 }));
});
