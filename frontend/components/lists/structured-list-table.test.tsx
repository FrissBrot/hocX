import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { StructuredListTable } from "./structured-list-table";
import { StructuredListDefinition, StructuredListEntry } from "@/types/api";

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
