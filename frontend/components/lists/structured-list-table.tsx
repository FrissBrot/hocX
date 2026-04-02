"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { Modal } from "@/components/ui/modal";
import { formatDateRange } from "@/lib/utils/format";
import {
  EventSummary,
  ParticipantSummary,
  StructuredListDefinition,
  StructuredListEntry,
  StructuredListValueType,
} from "@/types/api";

type StructuredListValue = Record<string, unknown>;
type StructuredListColumnKey = "column_one_value" | "column_two_value";

type StructuredListTableProps = {
  definition: StructuredListDefinition;
  entries: StructuredListEntry[];
  availableParticipants: ParticipantSummary[];
  availableEvents: EventSummary[];
  editable?: boolean;
  emptyMessage?: string;
  onCreateEntry: (payload: {
    sort_index: number;
    column_one_value: StructuredListValue;
    column_two_value: StructuredListValue;
  }) => Promise<boolean>;
  onUpdateEntry: (
    entryId: number,
    payload: Partial<{
      sort_index: number;
      column_one_value: StructuredListValue;
      column_two_value: StructuredListValue;
    }>
  ) => Promise<boolean>;
  onDeleteEntry: (entryId: number) => Promise<void>;
};

type ParticipantPickerState = {
  columnKey: StructuredListColumnKey;
  selectedIds: number[];
  entryId?: number;
  isNewRow: boolean;
};

function compareIsoDate(left: string | null | undefined, right: string | null | undefined) {
  if (!left && !right) return 0;
  if (!left) return -1;
  if (!right) return 1;
  return left.localeCompare(right);
}

function emptyValueForType(valueType: StructuredListValueType): StructuredListValue {
  switch (valueType) {
    case "participant":
      return { participant_id: null };
    case "participants":
      return { participant_ids: [] };
    case "event":
      return { event_id: null };
    default:
      return { text_value: "" };
  }
}

function normalizeValueForType(valueType: StructuredListValueType, rawValue: StructuredListValue): StructuredListValue {
  if (valueType === "participant") {
    const participantId = Number(rawValue.participant_id ?? 0);
    return participantId ? { participant_id: participantId } : { participant_id: null };
  }
  if (valueType === "participants") {
    const participantIds = Array.isArray(rawValue.participant_ids)
      ? rawValue.participant_ids.map((participantId) => Number(participantId)).filter(Boolean)
      : [];
    return { participant_ids: participantIds };
  }
  if (valueType === "event") {
    const eventId = Number(rawValue.event_id ?? 0);
    return eventId ? { event_id: eventId } : { event_id: null };
  }
  return { text_value: String(rawValue.text_value ?? "") };
}

function hasValueContent(valueType: StructuredListValueType, rawValue: StructuredListValue) {
  const value = normalizeValueForType(valueType, rawValue);
  if (valueType === "participant") {
    return Number(value.participant_id ?? 0) > 0;
  }
  if (valueType === "participants") {
    return Array.isArray(value.participant_ids) && value.participant_ids.length > 0;
  }
  if (valueType === "event") {
    return Number(value.event_id ?? 0) > 0;
  }
  return String(value.text_value ?? "").trim().length > 0;
}

function valueSummary(
  valueType: StructuredListValueType,
  rawValue: StructuredListValue,
  participants: ParticipantSummary[],
  events: EventSummary[]
) {
  const value = normalizeValueForType(valueType, rawValue);
  if (valueType === "participant") {
    const participant = participants.find((item) => item.id === Number(value.participant_id ?? 0));
    return participant?.display_name ?? "—";
  }
  if (valueType === "participants") {
    const selectedIds = Array.isArray(value.participant_ids) ? value.participant_ids.map(Number) : [];
    if (!selectedIds.length) {
      return "—";
    }
    const selectedParticipants = participants.filter((item) => selectedIds.includes(item.id));
    if (!selectedParticipants.length) {
      return `${selectedIds.length} ausgewaehlt`;
    }
    return selectedParticipants.map((item) => item.display_name).join(", ");
  }
  if (valueType === "event") {
    const eventRow = events.find((item) => item.id === Number(value.event_id ?? 0));
    return eventRow ? `${formatDateRange(eventRow.event_date, eventRow.event_end_date)} · ${eventRow.title}` : "—";
  }
  return String(value.text_value ?? "").trim() || "—";
}

function createNewRowDraft(definition: StructuredListDefinition) {
  return {
    column_one_value: emptyValueForType(definition.column_one_value_type),
    column_two_value: emptyValueForType(definition.column_two_value_type),
  };
}

export function StructuredListTable({
  definition,
  entries,
  availableParticipants,
  availableEvents,
  editable = true,
  emptyMessage = "Noch keine Eintraege.",
  onCreateEntry,
  onUpdateEntry,
  onDeleteEntry,
}: StructuredListTableProps) {
  const sortedEvents = useMemo(
    () => [...availableEvents].sort((left, right) => compareIsoDate(left.event_date, right.event_date)),
    [availableEvents]
  );
  const [entryDrafts, setEntryDrafts] = useState<
    Record<number, Partial<{ column_one_value: StructuredListValue; column_two_value: StructuredListValue }>>
  >({});
  const [showNewRow, setShowNewRow] = useState(false);
  const [newRowDraft, setNewRowDraft] = useState(() => createNewRowDraft(definition));
  const [creatingNewRow, setCreatingNewRow] = useState(false);
  const [participantPicker, setParticipantPicker] = useState<ParticipantPickerState | null>(null);
  const [participantSearch, setParticipantSearch] = useState("");
  const rowTimers = useRef<Record<number, number>>({});
  const newRowTimer = useRef<number | null>(null);

  useEffect(() => {
    Object.values(rowTimers.current).forEach((timerId) => window.clearTimeout(timerId));
    rowTimers.current = {};
    if (newRowTimer.current) {
      window.clearTimeout(newRowTimer.current);
      newRowTimer.current = null;
    }
    setShowNewRow(false);
    setNewRowDraft(createNewRowDraft(definition));
    setEntryDrafts({});
    setParticipantPicker(null);
    setParticipantSearch("");
  }, [definition.id]);

  useEffect(() => {
    return () => {
      Object.values(rowTimers.current).forEach((timerId) => window.clearTimeout(timerId));
      if (newRowTimer.current) {
        window.clearTimeout(newRowTimer.current);
      }
    };
  }, []);

  function nextSortIndex() {
    return (entries.reduce((highest, entry) => Math.max(highest, Number(entry.sort_index) || 0), 0) || 0) + 10;
  }

  function hasNewRowContent(nextDraft: { column_one_value: StructuredListValue; column_two_value: StructuredListValue }) {
    return (
      hasValueContent(definition.column_one_value_type, nextDraft.column_one_value) ||
      hasValueContent(definition.column_two_value_type, nextDraft.column_two_value)
    );
  }

  function queueRowSave(
    entryId: number,
    payload: Partial<{ column_one_value: StructuredListValue; column_two_value: StructuredListValue }>
  ) {
    const nextDraft = {
      ...(entryDrafts[entryId] ?? {}),
      ...payload,
    };
    setEntryDrafts((current) => ({
      ...current,
      [entryId]: nextDraft,
    }));
    if (rowTimers.current[entryId]) {
      window.clearTimeout(rowTimers.current[entryId]);
    }
    rowTimers.current[entryId] = window.setTimeout(async () => {
      const saved = await onUpdateEntry(entryId, nextDraft);
      if (saved) {
        setEntryDrafts((current) => {
          if (!current[entryId]) {
            return current;
          }
          const next = { ...current };
          delete next[entryId];
          return next;
        });
      }
    }, 500);
  }

  function resetNewRow() {
    if (newRowTimer.current) {
      window.clearTimeout(newRowTimer.current);
      newRowTimer.current = null;
    }
    setCreatingNewRow(false);
    setShowNewRow(false);
    setNewRowDraft(createNewRowDraft(definition));
  }

  function scheduleNewRowCreate(nextDraft: { column_one_value: StructuredListValue; column_two_value: StructuredListValue }) {
    if (newRowTimer.current) {
      window.clearTimeout(newRowTimer.current);
      newRowTimer.current = null;
    }
    if (!hasNewRowContent(nextDraft)) {
      return;
    }
    newRowTimer.current = window.setTimeout(async () => {
      setCreatingNewRow(true);
      const saved = await onCreateEntry({
        sort_index: nextSortIndex(),
        column_one_value: normalizeValueForType(definition.column_one_value_type, nextDraft.column_one_value),
        column_two_value: normalizeValueForType(definition.column_two_value_type, nextDraft.column_two_value),
      });
      setCreatingNewRow(false);
      if (saved) {
        resetNewRow();
      }
    }, 500);
  }

  function patchNewRow(
    payload: Partial<{ column_one_value: StructuredListValue; column_two_value: StructuredListValue }>
  ) {
    setNewRowDraft((current) => {
      const nextDraft = { ...current, ...payload };
      scheduleNewRowCreate(nextDraft);
      return nextDraft;
    });
  }

  function rowValue(entry: StructuredListEntry, columnKey: StructuredListColumnKey) {
    return normalizeValueForType(
      columnKey === "column_one_value" ? definition.column_one_value_type : definition.column_two_value_type,
      ((entryDrafts[entry.id] ?? {})[columnKey] as StructuredListValue | undefined) ??
        (entry[columnKey] as StructuredListValue)
    );
  }

  function openParticipantPicker(
    columnKey: StructuredListColumnKey,
    value: StructuredListValue,
    options: { entryId?: number; isNewRow: boolean }
  ) {
    setParticipantPicker({
      columnKey,
      entryId: options.entryId,
      isNewRow: options.isNewRow,
      selectedIds: Array.isArray(value.participant_ids) ? value.participant_ids.map(Number) : [],
    });
    setParticipantSearch("");
  }

  function applyParticipantPicker() {
    if (!participantPicker) {
      return;
    }
    const nextValue = { participant_ids: [...participantPicker.selectedIds] };
    if (participantPicker.isNewRow) {
      patchNewRow({ [participantPicker.columnKey]: nextValue });
    } else if (participantPicker.entryId) {
      queueRowSave(participantPicker.entryId, { [participantPicker.columnKey]: nextValue });
    }
    setParticipantPicker(null);
    setParticipantSearch("");
  }

  function renderEditableCell(
    entryId: number | null,
    columnKey: StructuredListColumnKey,
    valueType: StructuredListValueType,
    value: StructuredListValue,
    options: { isNewRow: boolean; disabled?: boolean }
  ) {
    if (valueType === "participant") {
      return (
        <select
          value={String(value.participant_id ?? "")}
          disabled={options.disabled}
          onChange={(event) => {
            const nextValue = { participant_id: event.target.value ? Number(event.target.value) : null };
            if (options.isNewRow) {
              patchNewRow({ [columnKey]: nextValue });
            } else if (entryId) {
              queueRowSave(entryId, { [columnKey]: nextValue });
            }
          }}
        >
          <option value="">Teilnehmer</option>
          {availableParticipants.map((participant) => (
            <option key={`${definition.id}-${columnKey}-participant-${participant.id}`} value={participant.id}>
              {participant.display_name}
            </option>
          ))}
        </select>
      );
    }

    if (valueType === "participants") {
      return (
        <button
          type="button"
          className="button-ghost structured-list-picker"
          disabled={options.disabled}
          onClick={() => openParticipantPicker(columnKey, value, { entryId: entryId ?? undefined, isNewRow: options.isNewRow })}
        >
          {valueSummary(valueType, value, availableParticipants, sortedEvents)}
        </button>
      );
    }

    if (valueType === "event") {
      return (
        <select
          value={String(value.event_id ?? "")}
          disabled={options.disabled}
          onChange={(event) => {
            const nextValue = { event_id: event.target.value ? Number(event.target.value) : null };
            if (options.isNewRow) {
              patchNewRow({ [columnKey]: nextValue });
            } else if (entryId) {
              queueRowSave(entryId, { [columnKey]: nextValue });
            }
          }}
        >
          <option value="">Termin</option>
          {sortedEvents.map((eventRow) => (
            <option key={`${definition.id}-${columnKey}-event-${eventRow.id}`} value={eventRow.id}>
              {formatDateRange(eventRow.event_date, eventRow.event_end_date)} · {eventRow.title}
            </option>
          ))}
        </select>
      );
    }

    return (
      <input
        className="structured-list-field"
        value={String(value.text_value ?? "")}
        disabled={options.disabled}
        onChange={(event) => {
          const nextValue = { text_value: event.target.value };
          if (options.isNewRow) {
            patchNewRow({ [columnKey]: nextValue });
          } else if (entryId) {
            queueRowSave(entryId, { [columnKey]: nextValue });
          }
        }}
        placeholder="Wert"
      />
    );
  }

  const filteredParticipants = useMemo(() => {
    const query = participantSearch.trim().toLowerCase();
    return availableParticipants.filter((participant) => {
      if (!query) {
        return true;
      }
      return participant.display_name.toLowerCase().includes(query);
    });
  }, [availableParticipants, participantSearch]);

  const sortedEntries = useMemo(
    () => [...entries].sort((left, right) => (left.sort_index - right.sort_index) || (left.id - right.id)),
    [entries]
  );

  return (
    <>
      <div className="event-table-wrap">
        <table className="data-table event-table event-table-compact structured-list-table">
          <thead>
            <tr>
              <th>{definition.column_one_title}</th>
              <th>{definition.column_two_title}</th>
              {editable ? (
                <th className="event-column-actions" aria-label="Aktionen">
                  <button
                    type="button"
                    className="button-ghost button-icon"
                    title="Listenzeile hinzufuegen"
                    disabled={showNewRow || creatingNewRow}
                    onClick={() => {
                      setShowNewRow(true);
                      setNewRowDraft(createNewRowDraft(definition));
                    }}
                  >
                    +
                  </button>
                </th>
              ) : null}
            </tr>
          </thead>
          <tbody>
            {showNewRow ? (
              <tr className="event-row-new">
                <td>
                  {renderEditableCell(null, "column_one_value", definition.column_one_value_type, newRowDraft.column_one_value, {
                    isNewRow: true,
                    disabled: creatingNewRow,
                  })}
                </td>
                <td>
                  {renderEditableCell(null, "column_two_value", definition.column_two_value_type, newRowDraft.column_two_value, {
                    isNewRow: true,
                    disabled: creatingNewRow,
                  })}
                </td>
                {editable ? (
                  <td>
                    <div className="event-row-actions">
                      <button
                        type="button"
                        className="button-ghost button-icon button-icon-danger"
                        title="Neue Listenzeile verwerfen"
                        disabled={creatingNewRow}
                        onClick={resetNewRow}
                      >
                        x
                      </button>
                    </div>
                  </td>
                ) : null}
              </tr>
            ) : null}
            {sortedEntries.length ? (
              sortedEntries.map((entry) => {
                const firstValue = rowValue(entry, "column_one_value");
                const secondValue = rowValue(entry, "column_two_value");
                return (
                  <tr key={entry.id}>
                    <td>
                      {editable
                        ? renderEditableCell(entry.id, "column_one_value", definition.column_one_value_type, firstValue, {
                            isNewRow: false,
                          })
                        : valueSummary(definition.column_one_value_type, firstValue, availableParticipants, sortedEvents)}
                    </td>
                    <td>
                      {editable
                        ? renderEditableCell(entry.id, "column_two_value", definition.column_two_value_type, secondValue, {
                            isNewRow: false,
                          })
                        : valueSummary(definition.column_two_value_type, secondValue, availableParticipants, sortedEvents)}
                    </td>
                    {editable ? (
                      <td>
                        <div className="event-row-actions">
                          <button
                            type="button"
                            className="button-ghost button-icon button-icon-danger"
                            title="Listenzeile loeschen"
                            onClick={() => void onDeleteEntry(entry.id)}
                          >
                            x
                          </button>
                        </div>
                      </td>
                    ) : null}
                  </tr>
                );
              })
            ) : !showNewRow ? (
              <tr>
                <td colSpan={editable ? 3 : 2}>
                  <span className="muted">{emptyMessage}</span>
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      <Modal
        open={Boolean(participantPicker)}
        onClose={() => {
          setParticipantPicker(null);
          setParticipantSearch("");
        }}
        title="Teilnehmer waehlen"
        description="Mehrfachauswahl fuer dieses Listenfeld."
      >
        <div className="grid">
          <label className="field-stack">
            <span className="field-label">Suche</span>
            <input
              value={participantSearch}
              onChange={(event) => setParticipantSearch(event.target.value)}
              placeholder="Teilnehmer filtern"
            />
          </label>
          <div className="participant-check-grid">
            {filteredParticipants.map((participant) => {
              const checked = participantPicker?.selectedIds.includes(participant.id) ?? false;
              return (
                <label
                  key={`structured-list-picker-${participant.id}`}
                  className={`participant-check-card${checked ? " participant-check-card-active" : ""}`}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={(event) =>
                      setParticipantPicker((current) =>
                        current
                          ? {
                              ...current,
                              selectedIds: event.target.checked
                                ? [...current.selectedIds, participant.id]
                                : current.selectedIds.filter((entryId) => entryId !== participant.id),
                            }
                          : current
                      )
                    }
                  />
                  <span>{participant.display_name}</span>
                </label>
              );
            })}
          </div>
          <div className="table-toolbar-actions">
            <button type="button" className="button-inline" onClick={applyParticipantPicker}>
              Auswahl uebernehmen
            </button>
          </div>
        </div>
      </Modal>
    </>
  );
}
