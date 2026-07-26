"use client";

import { Modal } from "@/components/ui/modal";
import { StructuredListTable } from "@/components/lists/structured-list-table";
import {
  EventSummary,
  ParticipantSummary,
  StructuredListDefinition,
  StructuredListEntry,
} from "@/types/api";

type SortColumn = "" | "column_one" | "column_two";

type EntryPayload = {
  sort_index: number;
  column_one_value: Record<string, unknown>;
  column_two_value: Record<string, unknown>;
};

type StructuredListEditModalProps = {
  open: boolean;
  onClose: () => void;
  definition: StructuredListDefinition;
  entries: StructuredListEntry[];
  availableParticipants: ParticipantSummary[];
  availableEvents: EventSummary[];
  groupByColumn: SortColumn;
  sortByColumn: SortColumn;
  sortDirection: "asc" | "desc";
  onChangeGroupBy: (value: SortColumn) => void;
  onChangeSortBy: (value: SortColumn) => void;
  onChangeSortDirection: (value: "asc" | "desc") => void;
  onCreateEntry: (payload: EntryPayload) => Promise<boolean>;
  onUpdateEntry: (entryId: number, payload: Partial<EntryPayload>) => Promise<boolean>;
  onDeleteEntry: (entryId: number) => Promise<void>;
};

/**
 * Planning-mode ("geplant") popup for editing the list behind a "Tabelle aus Liste"
 * block. Reuses the exact same StructuredListTable + callbacks that used to render
 * inline in the protocol editor — only the sort/group controls and the editable
 * table now live here instead of inline, analogous to the Listen-Tab editor.
 */
export function StructuredListEditModal({
  open,
  onClose,
  definition,
  entries,
  availableParticipants,
  availableEvents,
  groupByColumn,
  sortByColumn,
  sortDirection,
  onChangeGroupBy,
  onChangeSortBy,
  onChangeSortDirection,
  onCreateEntry,
  onUpdateEntry,
  onDeleteEntry,
}: StructuredListEditModalProps) {
  const listColOptions: { value: SortColumn; label: string }[] = [
    { value: "column_one", label: definition.column_one_title },
    { value: "column_two", label: definition.column_two_title },
  ];

  return (
    <Modal open={open} onClose={onClose} title="Liste bearbeiten" description={definition.name} size="wide">
      <div className="list-block-config-bar">
        <label className="list-block-config-item">
          <span className="list-block-config-label">Gruppieren</span>
          <select value={groupByColumn} onChange={(e) => onChangeGroupBy((e.target.value || "") as SortColumn)}>
            <option value="">Keine Gruppierung</option>
            {listColOptions.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label className="list-block-config-item">
          <span className="list-block-config-label">Sortieren</span>
          <select
            value={sortByColumn}
            onChange={(e) => onChangeSortBy((e.target.value || "") as SortColumn)}
          >
            <option value="">Manuell</option>
            {listColOptions.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label className="list-block-config-item">
          <select
            value={sortDirection}
            disabled={!sortByColumn}
            onChange={(e) => onChangeSortDirection(e.target.value === "desc" ? "desc" : "asc")}
          >
            <option value="asc">A–Z</option>
            <option value="desc">Z–A</option>
          </select>
        </label>
      </div>
      <StructuredListTable
        definition={definition}
        entries={entries}
        availableParticipants={availableParticipants}
        availableEvents={availableEvents}
        editable
        fullWidth
        emptyMessage="Noch keine Einträge in dieser Liste."
        groupByColumn={groupByColumn}
        sortByColumn={sortByColumn}
        sortDirection={sortDirection}
        onCreateEntry={onCreateEntry}
        onUpdateEntry={onUpdateEntry}
        onDeleteEntry={onDeleteEntry}
      />
    </Modal>
  );
}
