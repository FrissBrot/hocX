"use client";

import { useParticipantSelectable } from "@/contexts/participant-date-context";
import { useParticipantNameSource } from "@/contexts/participant-directory-context";

import { Fragment, ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { ListValueTypeIcon } from "@/components/lists/list-value-type-icon";
import { Badge } from "@/components/ui/badge";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { SearchInput } from "@/components/ui/search-input";
import { localDateToday } from "@/lib/utils/participant-membership";
import { Modal } from "@/components/ui/modal";
import { ActionIcon } from "@/components/ui/action-icons";
import { SearchableMultiSelect, SearchableSelect } from "@/components/ui/searchable-select";
import { TrackedChangeHideButton } from "@/components/ui/tracked-change-hide-button";
import { formatDate, formatDateRange } from "@/lib/utils/format";
import {
  EventSummary,
  ListColumn,
  ListValues,
  ParticipantSummary,
  StructuredListDefinition,
  StructuredListEntry,
  StructuredListValueType,
} from "@/types/api";

type StructuredListValue = Record<string, unknown>;
/** Spalten-Key (ListColumn.id) - undurchsichtig, nie auf einen bestimmten Wert prüfen. */
type StructuredListColumnKey = string;

export type TrackedEntryInfo = {
  status: "added" | "changed" | "removed";
  before?: ListValues;
};

type StructuredListTableProps = {
  definition: StructuredListDefinition;
  entries: StructuredListEntry[];
  availableParticipants: ParticipantSummary[];
  availableEvents: EventSummary[];
  editable?: boolean;
  highlightDepartedParticipants?: boolean;
  /** Independent of `editable` - hides the "add row" control even while existing rows
   * are editable/deletable. Used by the historical-snapshot view: an unlocked
   * historical row can be edited or removed, but new rows were never part of that
   * cycle's data and aren't something the guarded historical-edit API supports adding. */
  allowCreate?: boolean;
  fullWidth?: boolean;
  /** Kompakte Stammdatenansicht mit Teilnehmerchips und Zeilenaktion im Fuss. */
  masterList?: boolean;
  /** Nur die Anzeige filtern; neue Zeilen bleiben hinter dem vollständigen Bestand. */
  visibleEntryIds?: string[];
  /** Protokoll-Darstellung eines mit einer Stammliste verknüpften Tabellenblocks: Zeilen
   * kommen fix aus der Liste, zugeteilte Personen als Chips, Besetzungsgrad oben.
   * `highlightEmpty` kommt aus der Block-Konfiguration im Template. Gilt nur ohne Gruppierung. */
  protocolView?: { highlightEmpty?: boolean };
  /** Nur Zeilen zeigen, deren Wert in `column` den Text enthält (Block-Option der Vorlage). */
  rowFilter?: { column: StructuredListColumnKey; text: string } | null;
  heading?: ReactNode;
  headingActions?: ReactNode;
  emptyMessage?: string;
  /** Spalten-Keys; leer = keine Gruppierung/Sortierung. Unbekannte Keys werden ignoriert. */
  groupByColumn?: StructuredListColumnKey;
  sortByColumn?: StructuredListColumnKey;
  sortDirection?: "asc" | "desc";
  /** Sichtbare Spalten in dieser Reihenfolge (Block-Option); fehlt sie, alle Spalten der Liste. */
  visibleColumns?: StructuredListColumnKey[] | null;
  onHeaderSort?: (column: StructuredListColumnKey) => void;
  entryTrackedStatusById?: Record<string, TrackedEntryInfo>;
  onAcceptTrackedEntry?: (entryId: string) => void;
  onCreateEntry: (payload: { sort_index: number; values: ListValues }) => Promise<boolean>;
  onUpdateEntry: (entryId: string, payload: Partial<{ sort_index: number; values: ListValues }>) => Promise<boolean>;
  onDeleteEntry: (entryId: string) => Promise<void>;
};

type ParticipantPickerState = {
  columnKey: StructuredListColumnKey;
  selectedIds: string[];
  entryId?: string;
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
    const participantId = typeof rawValue.participant_id === "string" && rawValue.participant_id ? rawValue.participant_id : null;
    return { participant_id: participantId };
  }
  if (valueType === "participants") {
    const participantIds = Array.isArray(rawValue.participant_ids)
      ? rawValue.participant_ids.map((participantId) => String(participantId)).filter(Boolean)
      : [];
    return { participant_ids: participantIds };
  }
  if (valueType === "event") {
    const eventId = typeof rawValue.event_id === "string" && rawValue.event_id ? rawValue.event_id : null;
    return { event_id: eventId };
  }
  return { text_value: String(rawValue.text_value ?? "") };
}

function valuesEqual(left: StructuredListValue | undefined, right: StructuredListValue | undefined): boolean {
  return JSON.stringify(left ?? {}) === JSON.stringify(right ?? {});
}

function hasValueContent(valueType: StructuredListValueType, rawValue: StructuredListValue) {
  const value = normalizeValueForType(valueType, rawValue);
  if (valueType === "participant") {
    return value.participant_id != null;
  }
  if (valueType === "participants") {
    return Array.isArray(value.participant_ids) && value.participant_ids.length > 0;
  }
  if (valueType === "event") {
    return value.event_id != null;
  }
  return String(value.text_value ?? "").trim().length > 0;
}

type TFunc = (key: string, values?: Record<string, string | number | Date>) => string;

function valueSummary(
  valueType: StructuredListValueType,
  rawValue: StructuredListValue,
  participants: ParticipantSummary[],
  events: EventSummary[],
  t: TFunc
) {
  const value = normalizeValueForType(valueType, rawValue);
  if (valueType === "participant") {
    const participant = participants.find((item) => item.id === value.participant_id);
    return typeof rawValue.participant_name === "string" ? rawValue.participant_name : participant?.display_name ?? "—";
  }
  if (valueType === "participants") {
    const selectedIds = Array.isArray(value.participant_ids) ? (value.participant_ids as string[]) : [];
    if (!selectedIds.length) {
      return "—";
    }
    if (Array.isArray(rawValue.participant_names) && rawValue.participant_names.some(Boolean)) {
      return rawValue.participant_names.filter(Boolean).join(", ");
    }
    const selectedParticipants = participants.filter((item) => selectedIds.includes(item.id));
    if (!selectedParticipants.length) {
      return t("selectedCount", { count: selectedIds.length });
    }
    return selectedParticipants.map((item) => item.display_name).join(", ");
  }
  if (valueType === "event") {
    const eventRow = events.find((item) => item.id === value.event_id);
    return eventRow ? `${formatDateRange(eventRow.event_date, eventRow.event_end_date)} · ${eventRow.title}` : "—";
  }
  return String(value.text_value ?? "").trim() || "—";
}

function createNewRowDraft(definition: StructuredListDefinition): ListValues {
  return Object.fromEntries(definition.columns.map((column) => [column.id, emptyValueForType(column.value_type)]));
}

function valueSortText(
  valueType: StructuredListValueType,
  rawValue: StructuredListValue,
  participants: ParticipantSummary[],
  events: EventSummary[]
) {
  const value = normalizeValueForType(valueType, rawValue);
  if (valueType === "participant") {
    const participant = participants.find((item) => item.id === value.participant_id);
    return typeof rawValue.participant_name === "string" ? rawValue.participant_name : participant?.display_name ?? "";
  }
  if (valueType === "participants") {
    const selectedIds = Array.isArray(value.participant_ids) ? (value.participant_ids as string[]) : [];
    if (!selectedIds.length) {
      return "";
    }
    if (Array.isArray(rawValue.participant_names) && rawValue.participant_names.some(Boolean)) {
      return rawValue.participant_names.filter(Boolean).join(", ");
    }
    return participants
      .filter((item) => selectedIds.includes(item.id))
      .map((item) => item.display_name)
      .join(", ");
  }
  if (valueType === "event") {
    const eventRow = events.find((item) => item.id === value.event_id);
    return eventRow ? `${eventRow.title} ${formatDate(eventRow.event_date)}`.trim() : "";
  }
  return String(value.text_value ?? "").trim();
}

export function StructuredListTable({
  definition,
  entries,
  availableParticipants,
  availableEvents,
  editable = true,
  highlightDepartedParticipants = false,
  allowCreate = true,
  fullWidth = false,
  masterList = false,
  visibleEntryIds,
  protocolView,
  rowFilter = null,
  heading,
  headingActions,
  emptyMessage,
  groupByColumn = "",
  sortByColumn = "",
  sortDirection = "asc",
  visibleColumns = null,
  onHeaderSort,
  entryTrackedStatusById,
  onAcceptTrackedEntry,
  onCreateEntry,
  onUpdateEntry,
  onDeleteEntry,
}: StructuredListTableProps) {
  const isParticipantSelectable = useParticipantSelectable();
  const participantNames = useParticipantNameSource(availableParticipants);
  const isPickableParticipant = useCallback((participant: ParticipantSummary) =>
    isParticipantSelectable(participant) && availableParticipants.some((entry) => entry.id === participant.id),
  [availableParticipants, isParticipantSelectable]);
  const t = useTranslations("lists.table");
  const listT = useTranslations("lists");
  const today = localDateToday();
  const resolvedEmptyMessage = emptyMessage ?? t("emptyMessage");
  const sortedEvents = useMemo(
    () => [...availableEvents].sort((left, right) => compareIsoDate(left.event_date, right.event_date)),
    [availableEvents]
  );
  const columnTypes = useMemo(
    () => Object.fromEntries(definition.columns.map((column) => [column.id, column.value_type])) as Record<string, StructuredListValueType>,
    [definition.columns]
  );
  // Angezeigte Spalten: Auswahl des Blocks (unbekannte Keys fallen weg), sonst alle der Liste
  const columns: ListColumn[] = useMemo(() => {
    const ordered = [...definition.columns].sort((left, right) => left.sort_index - right.sort_index);
    if (!visibleColumns?.length) return ordered;
    const chosen = visibleColumns.map((key) => ordered.find((column) => column.id === key)).filter((column): column is ListColumn => Boolean(column));
    return chosen.length ? chosen : ordered;
  }, [definition.columns, visibleColumns]);
  const knownColumn = (key: string | null | undefined): key is string => Boolean(key && columnTypes[key]);
  const activeGroupBy = knownColumn(groupByColumn) ? groupByColumn : "";
  const activeSortBy = knownColumn(sortByColumn) ? sortByColumn : "";
  const [entryDrafts, setEntryDrafts] = useState<Record<string, ListValues>>({});
  const [showNewRow, setShowNewRow] = useState(false);
  const [newRowDraft, setNewRowDraft] = useState(() => createNewRowDraft(definition));
  const [creatingNewRow, setCreatingNewRow] = useState(false);
  const [participantPicker, setParticipantPicker] = useState<ParticipantPickerState | null>(null);
  const [participantSearch, setParticipantSearch] = useState("");
  const [protocolFilter, setProtocolFilter] = useState<"all" | "open" | "changed">("all");
  // Protokoll-Ansicht: Suche und Sortierung per Spaltenkopf filtern/ordnen nur die Anzeige,
  // die Vorlage (sort_by/sort_index) bleibt unverändert; dritter Klick = Vorlagen-Reihenfolge.
  const [protocolSearch, setProtocolSearch] = useState("");
  const [protocolSort, setProtocolSort] = useState<{ column: StructuredListColumnKey; direction: "asc" | "desc" } | null>(null);
  const rowTimers = useRef<Record<string, number>>({});
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
    setProtocolSearch("");
    setProtocolSort(null);
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

  function hasNewRowContent(nextDraft: ListValues) {
    return definition.columns.some((column) => hasValueContent(column.value_type, nextDraft[column.id] ?? {}));
  }

  function queueRowSave(entryId: string, payload: ListValues) {
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
      const saved = await onUpdateEntry(entryId, {
        values: Object.fromEntries(Object.entries(nextDraft).map(([key, value]) => [key, normalizeValueForType(columnTypes[key] ?? "text", value)])),
      });
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

  function scheduleNewRowCreate(nextDraft: ListValues) {
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
        values: Object.fromEntries(
          definition.columns
            .map((column) => [column.id, normalizeValueForType(column.value_type, nextDraft[column.id] ?? {})] as const)
            .filter(([key, value]) => hasValueContent(columnTypes[key], value))
        ),
      });
      setCreatingNewRow(false);
      if (saved) {
        resetNewRow();
      }
    }, 500);
  }

  function patchNewRow(payload: ListValues) {
    setNewRowDraft((current) => {
      const nextDraft = { ...current, ...payload };
      scheduleNewRowCreate(nextDraft);
      return nextDraft;
    });
  }

  function rowValue(entry: StructuredListEntry, columnKey: StructuredListColumnKey) {
    const rawValue = (entryDrafts[entry.id] ?? {})[columnKey] ?? (entry.values ?? {})[columnKey] ?? {};
    // Eingefrorene Namen für Anzeige/Sortierung erhalten; Schreibwerte werden separat normalisiert.
    return { ...rawValue, ...normalizeValueForType(columnTypes[columnKey] ?? "text", rawValue) };
  }

  function displayColumnType(columnKey: StructuredListColumnKey): StructuredListValueType {
    return columnTypes[columnKey] ?? "text";
  }

  function entryDisplayText(entry: StructuredListEntry, columnKey: StructuredListColumnKey) {
    return valueSummary(displayColumnType(columnKey), rowValue(entry, columnKey), participantNames, sortedEvents, t);
  }

  function entrySortText(entry: StructuredListEntry, columnKey: StructuredListColumnKey) {
    return valueSortText(displayColumnType(columnKey), rowValue(entry, columnKey), participantNames, sortedEvents);
  }

  function openParticipantPicker(
    columnKey: StructuredListColumnKey,
    value: StructuredListValue,
    options: { entryId?: string; isNewRow: boolean }
  ) {
    setParticipantPicker({
      columnKey,
      entryId: options.entryId,
      isNewRow: options.isNewRow,
      selectedIds: Array.isArray(value.participant_ids) ? value.participant_ids.map(String) : [],
    });
    setParticipantSearch("");
  }

  function toggleParticipantPickerSelection(participantId: string) {
    setParticipantPicker((current) => {
      if (!current) {
        return current;
      }
      const nextIds = current.selectedIds.includes(participantId)
        ? current.selectedIds.filter((id) => id !== participantId)
        : [...current.selectedIds, participantId];
      const next = { ...current, selectedIds: nextIds };
      const nextValue = { participant_ids: [...nextIds] };
      if (next.isNewRow) {
        patchNewRow({ [next.columnKey]: nextValue });
      } else if (next.entryId) {
        queueRowSave(next.entryId, { [next.columnKey]: nextValue });
      }
      return next;
    });
  }

  function departedParticipant(participantId: unknown) {
    if (!highlightDepartedParticipants) return undefined;
    return participantNames.find((participant) => participant.id === participantId
      && participant.left_at && participant.left_at < today);
  }

  function departedTitle(participant: ParticipantSummary) {
    return t("departedParticipant", { date: formatDate(participant.left_at) });
  }

  function renderValueSummary(valueType: StructuredListValueType, value: StructuredListValue) {
    const ids = valueType === "participant" ? [value.participant_id]
      : valueType === "participants" && Array.isArray(value.participant_ids) ? value.participant_ids : [];
    if (!ids.some((id) => departedParticipant(id))) {
      return valueSummary(valueType, value, participantNames, sortedEvents, t);
    }
    return ids.map((id, index) => {
      const participant = participantNames.find((item) => item.id === id);
      const name = participant?.display_name ?? "";
      const departed = departedParticipant(id);
      return <Fragment key={String(id)}>
        {index > 0 ? ", " : null}
        {departed
          ? <Badge variant="warning"><span title={departedTitle(departed)}>{name}</span></Badge>
          : name}
      </Fragment>;
    });
  }

  function renderEditableCell(
    entryId: string | null,
    columnKey: StructuredListColumnKey,
    valueType: StructuredListValueType,
    value: StructuredListValue,
    options: { isNewRow: boolean; disabled?: boolean }
  ) {
    if (valueType === "participant") {
      const departed = departedParticipant(value.participant_id);
      if (masterList) {
        // Gleiche Chip-Optik wie bei "Mehrere Teilnehmer": Person als Chip (Klick öffnet Auswahl, × entfernt), leer als "Zuweisen".
        const id = (value.participant_id as string | null | undefined) ?? null;
        const save = (nextId: string | null) => {
          const nextValue = { participant_id: nextId };
          if (options.isNewRow) patchNewRow({ [columnKey]: nextValue });
          else if (entryId) queueRowSave(entryId, { [columnKey]: nextValue });
        };
        if (!id) {
          return <div className="list-manager-people">
            <SearchableSelect options={participantNames} isOptionSelectable={isPickableParticipant}
              getId={(person) => person.id} getLabel={(person) => person.display_name} value={null}
              onChange={(person) => save(person ? person.id : null)} disabled={options.disabled}
              placeholder={listT("assign")} className="list-manager-assign"
              triggerProps={{ "aria-label": t("participantPickerTitle") }} />
          </div>;
        }
        const participant = participantNames.find((person) => person.id === id);
        const name = String(value.participant_name || participant?.display_name || t("participantNullLabel"));
        return <div className="list-manager-people">
          <span className={`list-manager-person${departed ? " structured-list-departed" : ""}`} title={departed ? departedTitle(departed) : undefined}>
            <span className="list-manager-avatar">{name.split(/\s+/).map((part) => part[0]).slice(0, 2).join("")}</span>
            <SearchableSelect options={participantNames} isOptionSelectable={isPickableParticipant}
              getId={(person) => person.id} getLabel={(person) => person.display_name} value={id}
              onChange={(person) => save(person ? person.id : null)} disabled={options.disabled}
              placeholder={name} className="list-manager-person-select"
              triggerProps={{ "aria-label": t("participantPickerTitle") }} />
            <button type="button" className="button-icon-soft" disabled={options.disabled} aria-label={listT("removePerson", { name })} onClick={() => save(null)}>×</button>
          </span>
        </div>;
      }
      return (
        <SearchableSelect
          options={participantNames}
          className={departed ? "structured-list-departed" : undefined}
          triggerProps={departed ? { title: departedTitle(departed) } : undefined}
          isOptionSelectable={isPickableParticipant}
          getId={(participant) => participant.id}
          getLabel={(participant) => participant.display_name}
          value={(value.participant_id as string | null | undefined) ?? null}
          disabled={options.disabled}
          nullLabel={t("participantNullLabel")}
          onChange={(participant) => {
            const nextValue = { participant_id: participant ? participant.id : null };
            if (options.isNewRow) {
              patchNewRow({ [columnKey]: nextValue });
            } else if (entryId) {
              queueRowSave(entryId, { [columnKey]: nextValue });
            }
          }}
        />
      );
    }

    if (valueType === "participants") {
      if (masterList) {
        const ids = Array.isArray(value.participant_ids) ? value.participant_ids.map(String) : [];
        const save = (nextIds: string[]) => {
          const nextValue = { participant_ids: nextIds };
          if (options.isNewRow) patchNewRow({ [columnKey]: nextValue });
          else if (entryId) queueRowSave(entryId, { [columnKey]: nextValue });
        };
        return <div className="list-manager-people">
          {ids.map((id, index) => {
            const participant = participantNames.find((person) => person.id === id);
            const frozenNames = Array.isArray(value.participant_names) ? value.participant_names : [];
            const name = String(frozenNames[index] || participant?.display_name || t("participantNullLabel"));
            const departed = departedParticipant(id);
            return <span key={id} className={`list-manager-person${departed ? " structured-list-departed" : ""}`} title={departed ? departedTitle(departed) : undefined}>
              <span className="list-manager-avatar">{name.split(/\s+/).map((part) => part[0]).slice(0, 2).join("")}</span>{name}
              <button type="button" className="button-icon-soft" disabled={options.disabled} aria-label={listT("removePerson", { name })} onClick={() => save(ids.filter((personId) => personId !== id))}>×</button>
            </span>;
          })}
          <SearchableMultiSelect options={participantNames} isOptionSelectable={isPickableParticipant}
            getId={(person) => person.id} getLabel={(person) => person.display_name} values={ids}
            onChange={save} disabled={options.disabled} emptySelectionLabel={listT("assign")}
            className={ids.length ? "list-manager-add-person" : "list-manager-assign"}
            triggerProps={{ "aria-label": t("participantPickerTitle") }} />
        </div>;
      }
      return (
        <button
          type="button"
          className="button-ghost structured-list-picker"
          disabled={options.disabled}
          onClick={() => openParticipantPicker(columnKey, value, { entryId: entryId ?? undefined, isNewRow: options.isNewRow })}
        >
          {renderValueSummary(valueType, value)}
        </button>
      );
    }

    if (valueType === "event") {
      return (
        <SearchableSelect
          options={sortedEvents}
          getId={(eventRow) => eventRow.id}
          getLabel={(eventRow) => `${formatDateRange(eventRow.event_date, eventRow.event_end_date)} · ${eventRow.title}`}
          value={(value.event_id as string | null | undefined) ?? null}
          disabled={options.disabled}
          nullLabel={t("eventNullLabel")}
          onChange={(eventRow) => {
            const nextValue = { event_id: eventRow ? eventRow.id : null };
            if (options.isNewRow) {
              patchNewRow({ [columnKey]: nextValue });
            } else if (entryId) {
              queueRowSave(entryId, { [columnKey]: nextValue });
            }
          }}
        />
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
        placeholder={t("valuePlaceholder")}
      />
    );
  }

  const filteredParticipants = useMemo(() => {
    const query = participantSearch.trim().toLowerCase();
    return availableParticipants.filter(isParticipantSelectable).filter((participant) => {
      if (!query) {
        return true;
      }
      return participant.display_name.toLowerCase().includes(query);
    });
  }, [availableParticipants, participantSearch, isParticipantSelectable]);

  const textCollator = useMemo(
    () => new Intl.Collator("de", { sensitivity: "base", numeric: true }),
    []
  );

  const sortedEntries = useMemo(() => {
    const manualCompare = (left: StructuredListEntry, right: StructuredListEntry) =>
      (left.sort_index - right.sort_index) || compareIsoDate(left.created_at, right.created_at);

    const filterText = rowFilter?.text.trim().toLowerCase() ?? "";
    const filterColumn = rowFilter && knownColumn(rowFilter.column) ? rowFilter.column : "";
    return entries
      .filter((entry) => !visibleEntryIds || visibleEntryIds.includes(entry.id))
      .filter((entry) => !filterText || !filterColumn || entrySortText(entry, filterColumn).toLowerCase().includes(filterText))
      .sort((left, right) => {
      if (activeSortBy) {
        const leftText = entrySortText(left, activeSortBy).trim();
        const rightText = entrySortText(right, activeSortBy).trim();
        if (leftText && rightText) {
          const compared = textCollator.compare(leftText, rightText);
          if (compared !== 0) {
            return sortDirection === "desc" ? -compared : compared;
          }
        } else if (leftText) {
          return -1;
        } else if (rightText) {
          return 1;
        }
      }
      return manualCompare(left, right);
    });
  }, [entries, visibleEntryIds, rowFilter, entryDrafts, activeSortBy, sortDirection, textCollator, participantNames, sortedEvents, columnTypes]);

  const groupedEntries = useMemo(() => {
    if (!activeGroupBy) {
      return [];
    }
    const groups: Array<{ key: string; label: string; entries: StructuredListEntry[] }> = [];
    const groupIndex = new Map<string, number>();

    sortedEntries.forEach((entry) => {
      const rawLabel = entryDisplayText(entry, activeGroupBy);
      const label = rawLabel !== "—" ? rawLabel : t("noValue");
      // Ohne auflösbaren Namen nach dem Rohwert gruppieren, damit verschiedene (z. B. nicht
      // geladene) Personen nicht alle in einer gemeinsamen leeren Gruppe landen.
      const rawGroupValue = rowValue(entry, activeGroupBy);
      const key = entrySortText(entry, activeGroupBy).trim()
        || (hasValueContent(displayColumnType(activeGroupBy), rawGroupValue) ? `__raw__${JSON.stringify(rawGroupValue)}` : "__empty__");
      const existingIndex = groupIndex.get(key);
      if (existingIndex == null) {
        groupIndex.set(key, groups.length);
        groups.push({ key, label, entries: [entry] });
        return;
      }
      groups[existingIndex].entries.push(entry);
    });

    return groups;
  }, [activeGroupBy, sortedEntries, entryDrafts, participantNames, sortedEvents, columnTypes]);

  // Gruppiert und nur lesend: eine Zeile je Gruppenwert, die anderen Spalten zusammengefasst
  const groupedDisplayRows = useMemo(() => {
    if (!activeGroupBy || editable) {
      return [];
    }
    return groupedEntries.map((group) => ({
      key: group.key,
      cells: columns.map((column) => {
        if (column.id === activeGroupBy) return group.label;
        const merged = group.entries
          .map((entry) => String(entryDisplayText(entry, column.id) ?? "").replace(/\s+/g, " ").trim())
          .filter((value) => value && value !== "—");
        return merged.join(", ") || "—";
      }),
    }));
  }, [editable, activeGroupBy, groupedEntries, columns, entryDrafts, participantNames, sortedEvents, columnTypes]);

  function personRefs(valueType: StructuredListValueType, value: StructuredListValue | undefined) {
    if (!value) return [];
    if (valueType === "participant") {
      const id = typeof value.participant_id === "string" && value.participant_id ? value.participant_id : "";
      if (!id) return [];
      const frozenName = typeof value.participant_name === "string" ? value.participant_name : "";
      const name = frozenName || participantNames.find((person) => person.id === id)?.display_name || t("participantNullLabel");
      return [{ id, name }];
    }
    if (valueType !== "participants" || !Array.isArray(value.participant_ids)) return [];
    const frozenNames = Array.isArray(value.participant_names) ? value.participant_names : [];
    return value.participant_ids.map(String).filter(Boolean).map((id, index) => ({
      id,
      name: String(frozenNames[index] || participantNames.find((person) => person.id === id)?.display_name || t("participantNullLabel")),
    }));
  }

  function personInitials(name: string) {
    return name.split(/\s+/).filter(Boolean).map((part) => part[0]).slice(0, 2).join("").toUpperCase();
  }

  // Avatar-Farbe deterministisch aus dem Namen (5 Töne, gleicher Name = gleiche Farbe)
  function avatarToneClass(name: string) {
    let hash = 0;
    for (const char of name) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
    return `linked-list-avatar-tone-${hash % 5}`;
  }

  function renderProtocolView() {
    const isPersonType = (valueType: StructuredListValueType) => valueType === "participant" || valueType === "participants";
    // Rollen der Liste: die Spalte «Verantwortliche» bestimmt "besetzt", die Spalte «Bezeichnung»
    // ist die fixe Zeilenbeschriftung. Ohne Rollen: erste Personen-Spalte bzw. erste andere Spalte.
    const assignmentKey =
      (knownColumn(definition.responsible_column_id) ? definition.responsible_column_id : null)
      ?? columns.find((column) => isPersonType(column.value_type))?.id
      ?? columns[columns.length - 1]?.id ?? "";
    const labelKey =
      (knownColumn(definition.label_column_id) && definition.label_column_id !== assignmentKey ? definition.label_column_id : null)
      ?? columns.find((column) => column.id !== assignmentKey)?.id ?? assignmentKey;
    const assignmentType = displayColumnType(assignmentKey);
    const labelType = displayColumnType(labelKey);
    const extraColumns = columns.filter((column) => column.id !== assignmentKey && column.id !== labelKey);
    const titleOf = (key: string) => definition.columns.find((column) => column.id === key)?.title ?? "";
    const highlightEmpty = !!protocolView?.highlightEmpty;

    const rows = sortedEntries.map((entry) => {
      const tracked = entryTrackedStatusById?.[entry.id];
      const removed = tracked?.status === "removed";
      return { entry, tracked, removed, filled: !removed && hasValueContent(assignmentType, rowValue(entry, assignmentKey)) };
    });
    const activeRows = rows.filter((row) => !row.removed);
    const filledCount = activeRows.filter((row) => row.filled).length;
    const openCount = activeRows.length - filledCount;
    const changedCount = rows.filter((row) => !!row.tracked).length;
    const activeFilter = protocolFilter === "changed" && !changedCount ? "all" : protocolFilter;
    const searchText = protocolSearch.trim().toLocaleLowerCase();
    const searchKeys = [labelKey, ...extraColumns.map((column) => column.id), assignmentKey];
    const filteredRows = rows.filter((row) =>
      (activeFilter === "open" ? !row.removed && !row.filled : activeFilter === "changed" ? !!row.tracked : true)
      && (!searchText || searchKeys.some((key) => entrySortText(row.entry, key).toLocaleLowerCase().includes(searchText)))
    );
    const activeProtocolSort = protocolSort && searchKeys.includes(protocolSort.column) ? protocolSort : null;
    // Textspalten, in denen alle Werte Zahlen sind, rechtsbündig (Entwurf)
    const numericColumns = new Set(extraColumns.filter((column) => {
      if (column.value_type !== "text") return false;
      const values = rows.map((row) => entrySortText(row.entry, column.id).trim()).filter(Boolean);
      return values.length > 0 && values.every((value) => /^-?\d+(?:[.,']\d+)*$/.test(value));
    }).map((column) => column.id));
    const visibleRows = activeProtocolSort
      ? [...filteredRows].sort((left, right) => {
          const leftText = entrySortText(left.entry, activeProtocolSort.column).trim();
          const rightText = entrySortText(right.entry, activeProtocolSort.column).trim();
          // Leere Werte immer zuletzt, gleiche Werte in der bisherigen Reihenfolge
          if (!leftText || !rightText) return leftText ? -1 : rightText ? 1 : 0;
          const compared = textCollator.compare(leftText, rightText);
          return activeProtocolSort.direction === "desc" ? -compared : compared;
        })
      : filteredRows;
    // «brauchen Aufmerksamkeit» = Zeilen mit einer Status-Pille (offen/neu/geändert/entfernt)
    const attentionCount = rows.filter((row) => row.removed || !!row.tracked || (highlightEmpty && !row.filled)).length;
    const cycleSort = (column: StructuredListColumnKey) => setProtocolSort((current) =>
      current?.column !== column ? { column, direction: "asc" }
        : current.direction === "asc" ? { column, direction: "desc" }
        : null
    );
    const sortHeader = (column: StructuredListColumnKey, title: string) => {
      const active = activeProtocolSort?.column === column ? activeProtocolSort.direction : null;
      return (
        <th
          key={column}
          className={numericColumns.has(column) ? "linked-list-num" : undefined}
          aria-sort={active === "asc" ? "ascending" : active === "desc" ? "descending" : undefined}
        >
          <button
            type="button"
            className={`linked-list-sort${active ? " linked-list-sort-active" : ""}`}
            title={active === "asc" ? t("protocol.sortDesc") : active === "desc" ? t("protocol.sortReset") : t("protocol.sortAsc")}
            onClick={() => cycleSort(column)}
          >
            {title}
            {active ? <span className="linked-list-sort-mark" aria-hidden="true">{active === "asc" ? "▲" : "▼"}</span> : null}
          </button>
        </th>
      );
    };
    const showActions = editable || (changedCount > 0 && !!onAcceptTrackedEntry);
    const percent = activeRows.length ? Math.round((filledCount / activeRows.length) * 100) : 0;

    const saveAssignment = (entryId: string, current: string[], ids: string[]) => {
      // Einzelperson-Spalte: die neu angeklickte Person ersetzt die bisherige.
      const nextValue = assignmentType === "participant"
        ? { participant_id: ids.find((id) => !current.includes(id)) ?? (ids.includes(current[0]) ? current[0] : null) }
        : { participant_ids: ids };
      queueRowSave(entryId, { [assignmentKey]: nextValue });
    };

    function renderPeople(row: (typeof rows)[number]) {
      const value = rowValue(row.entry, assignmentKey);
      const current = personRefs(assignmentType, value);
      const before = row.tracked?.status === "changed" && row.tracked.before
        ? personRefs(assignmentType, row.tracked.before?.[assignmentKey])
        : null;
      const addedIds = new Set(
        row.tracked?.status === "added" ? current.map((person) => person.id)
          : before ? current.filter((person) => !before.some((old) => old.id === person.id)).map((person) => person.id)
          : []
      );
      const removedPeople = row.removed ? current
        : before ? before.filter((old) => !current.some((person) => person.id === old.id)) : [];
      const chipsEditable = editable && !row.removed;
      return (
        <div className="linked-list-people">
          {!row.removed && current.map((person) => {
            const departed = departedParticipant(person.id);
            const added = addedIds.has(person.id);
            return (
              <span
                key={person.id}
                className={`linked-list-person${added ? " linked-list-person-added" : ""}${departed ? " structured-list-departed" : ""}`}
                title={departed ? departedTitle(departed) : added ? t("protocol.addedPerson") : undefined}
              >
                <span className={`linked-list-avatar ${avatarToneClass(person.name)}`} aria-hidden="true">{personInitials(person.name)}</span>
                <span className="linked-list-person-name">{person.name}</span>
                {chipsEditable && (
                  <button
                    type="button"
                    className="linked-list-person-remove"
                    aria-label={listT("removePerson", { name: person.name })}
                    onClick={() => saveAssignment(row.entry.id, current.map((other) => other.id), current.filter((other) => other.id !== person.id).map((other) => other.id))}
                  >
                    ×
                  </button>
                )}
              </span>
            );
          })}
          {removedPeople.map((person) => (
            <span key={`removed-${person.id}`} className="linked-list-person linked-list-person-removed" title={t("protocol.removedPerson")}>
              <span className={`linked-list-avatar ${avatarToneClass(person.name)}`} aria-hidden="true">{personInitials(person.name)}</span>
              <span className="linked-list-person-name">{person.name}</span>
            </span>
          ))}
          {!row.removed && !current.length && (
            <span className={highlightEmpty ? "linked-list-empty linked-list-empty-highlight" : "linked-list-empty"}>
              {editable ? t("protocol.nobodyAssigned") : "—"}
            </span>
          )}
        </div>
      );
    }

    function renderOtherValue(row: (typeof rows)[number]) {
      const value = rowValue(row.entry, assignmentKey);
      const changed = row.tracked?.status === "changed" && !valuesEqual(value, row.tracked.before?.[assignmentKey]);
      return (
        <>
          {changed && (
            <div className="tracked-before-caption tracked-strike">
              {valueSummary(assignmentType, row.tracked?.before?.[assignmentKey] ?? {}, participantNames, sortedEvents, t)}
            </div>
          )}
          {editable && !row.removed
            ? renderEditableCell(row.entry.id, assignmentKey, assignmentType, value, { isNewRow: false })
            : <span className={row.removed ? "tracked-strike" : undefined}>{renderValueSummary(assignmentType, value)}</span>}
        </>
      );
    }

    return (
      <div className="linked-list-block">
        <div className="linked-list-summary">
          <span className="linked-list-summary-text">{t("protocol.summary", { count: rows.length, attention: attentionCount })}</span>
          {/* Besetzungsgrad nur, solange im Protokoll noch zugeteilt werden kann. */}
          {editable && (
            <>
          <div
            className="linked-list-progress"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={activeRows.length}
            aria-valuenow={filledCount}
            aria-label={t("protocol.occupied", { filled: filledCount, total: activeRows.length })}
          >
            <span className="linked-list-progress-bar" style={{ width: `${percent}%` }} />
          </div>
          <span className="linked-list-count">
            {t.rich("protocol.occupiedRich", { filled: filledCount, total: activeRows.length, strong: (chunks) => <strong>{chunks}</strong> })}
          </span>
            </>
          )}
          <FilterTabs
            value={activeFilter}
            onChange={setProtocolFilter}
            options={[
              { value: "all", label: t("protocol.filterAll"), count: activeRows.length },
              { value: "open", label: t("protocol.filterOpen"), count: openCount },
              ...(changedCount ? [{ value: "changed" as const, label: t("protocol.filterChanged"), count: changedCount }] : []),
            ]}
          />
          {rows.length ? (
            <SearchInput
              className="linked-list-search"
              value={protocolSearch}
              onChange={setProtocolSearch}
              placeholder={t("protocol.searchPlaceholderShort")}
              aria-label={t("protocol.searchPlaceholder", { name: definition.name })}
              clearLabel={t("protocol.searchClear")}
            />
          ) : null}
        </div>
        <div className="linked-list-table-wrap">
          <table className="data-table linked-list-table">
            <thead>
              <tr>
                {sortHeader(labelKey, titleOf(labelKey))}
                {extraColumns.map((column) => sortHeader(column.id, column.title))}
                {sortHeader(assignmentKey, titleOf(assignmentKey))}
                {showActions ? <th className="linked-list-actions" aria-label={t("actionsLabel")} /> : null}
              </tr>
            </thead>
            <tbody>
              {visibleRows.length ? visibleRows.map((row) => {
                const isOpen = !row.removed && !row.filled;
                // Bestehender Status (entfernt/neu/geändert/offen) als Pille statt Punkt
                const statusPill = row.removed ? <Badge variant="danger" dot>{t("protocol.statusRemoved")}</Badge>
                  : row.tracked?.status === "added" ? <Badge variant="success" dot>{t("protocol.statusAdded")}</Badge>
                  : row.tracked ? <Badge variant="success" dot>{t("protocol.statusChanged")}</Badge>
                  : isOpen && highlightEmpty ? <Badge variant="warning" dot>{t("protocol.statusOpen")}</Badge>
                  : null;
                const labelValue = rowValue(row.entry, labelKey);
                const labelChanged = row.tracked?.status === "changed" && !valuesEqual(labelValue, row.tracked.before?.[labelKey]);
                return (
                  <tr
                    key={row.entry.id}
                    className={`${isOpen && highlightEmpty ? "linked-list-row-open" : ""}${row.removed ? " linked-list-row-removed" : ""}`.trim() || undefined}
                  >
                    <td className="linked-list-label">
                      <span className={row.removed ? "tracked-strike" : undefined}>
                        {labelChanged && (
                          <span className="tracked-before-caption tracked-strike linked-list-label-before">
                            {valueSummary(labelType, row.tracked?.before?.[labelKey] ?? {}, participantNames, sortedEvents, t)}
                          </span>
                        )}
                        {renderValueSummary(labelType, labelValue)}
                      </span>
                      {statusPill ? <span className="linked-list-status">{statusPill}</span> : null}
                    </td>
                    {extraColumns.map((column) => (
                      <td key={column.id} className={numericColumns.has(column.id) ? "linked-list-num" : undefined}>
                        {editable && !row.removed
                          ? renderEditableCell(row.entry.id, column.id, column.value_type, rowValue(row.entry, column.id), { isNewRow: false })
                          : <span className={row.removed ? "tracked-strike" : undefined}>{renderValueSummary(column.value_type, rowValue(row.entry, column.id))}</span>}
                      </td>
                    ))}
                    <td>{isPersonType(assignmentType) ? renderPeople(row) : renderOtherValue(row)}</td>
                    {showActions ? (
                      <td className="linked-list-actions">
                        <div className="linked-list-actions-inner">
                          {row.tracked && onAcceptTrackedEntry && (
                            <TrackedChangeHideButton
                              title={row.removed ? t("hideRemovedEntryTitle") : undefined}
                              onAccept={() => onAcceptTrackedEntry(row.entry.id)}
                            />
                          )}
                          {editable && !row.removed && isPersonType(assignmentType) && (() => {
                            const currentIds = personRefs(assignmentType, rowValue(row.entry, assignmentKey)).map((person) => person.id);
                            return (
                            <SearchableMultiSelect
                              options={participantNames}
                              isOptionSelectable={isPickableParticipant}
                              getId={(person) => person.id}
                              getLabel={(person) => person.display_name}
                              values={currentIds}
                              onChange={(ids) => saveAssignment(row.entry.id, currentIds, ids)}
                              triggerLabel={t("protocol.addPerson")}
                              className="linked-list-add-person"
                              triggerProps={{ "aria-label": t("protocol.addPersonTo", { row: valueSortText(labelType, labelValue, participantNames, sortedEvents) }) }}
                            />
                            );
                          })()}
                        </div>
                      </td>
                    ) : null}
                  </tr>
                );
              }) : (
                <tr>
                  <td colSpan={extraColumns.length + (showActions ? 3 : 2)}>
                    <span className="muted">{rows.length ? t("protocol.filterEmpty") : resolvedEmptyMessage}</span>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="linked-list-footer">
          <span>{t("protocol.source", { name: definition.name })}</span>
          {changedCount > 0 && (
            <span className="linked-list-legend">
              <span><span className="linked-list-dot linked-list-dot-changed" aria-hidden="true" />{t("protocol.legendNew")}</span>
              <span><span className="linked-list-dot linked-list-dot-removed" aria-hidden="true" />{t("protocol.legendRemoved")}</span>
            </span>
          )}
        </div>
      </div>
    );
  }

  if (protocolView && !activeGroupBy) {
    return renderProtocolView();
  }

  return (
    <>
      {heading && (
        <div className="structured-list-heading">
          {heading}
          <div className="table-toolbar-actions">
          {headingActions}
          {editable && allowCreate && !masterList && (
            <button
              type="button"
              className="button-secondary"
              disabled={showNewRow || creatingNewRow}
              onClick={() => {
                setShowNewRow(true);
                setNewRowDraft(createNewRowDraft(definition));
              }}
            >
              {t("newEntryButton")}
            </button>
          )}
          </div>
        </div>
      )}
      <div className={`${heading ? "table-shell" : "event-table-wrap"}${fullWidth ? " structured-list-table-flat" : ""}${masterList ? " list-manager-table-shell" : ""}`} style={fullWidth ? { width: "100%" } : undefined}>
        <table className={`data-table structured-list-table${heading ? " data-table-lg" : " event-table event-table-compact"}${columns.length > 3 ? " structured-list-wide" : ""}`} style={fullWidth ? { width: "100%" } : undefined}>
          <thead>
            <tr>
              {columns.map((column) => (
                <th
                  key={column.id}
                  onClick={onHeaderSort ? () => onHeaderSort(column.id) : undefined}
                  className={onHeaderSort ? "structured-list-sortable" : undefined}
                >
                  {column.title}
                  {masterList && <span className="list-manager-column-type"><ListValueTypeIcon type={column.value_type} />{listT(`valueTypes.${column.value_type}`)}</span>}
                  {onHeaderSort && (
                    <span className={`structured-list-sort-mark${activeSortBy === column.id ? " structured-list-sort-mark-active" : ""}`} aria-hidden="true">
                      {activeSortBy === column.id ? (sortDirection === "asc" ? "↑" : "↓") : "↕"}
                    </span>
                  )}
                </th>
              ))}
              {editable ? (
                <th className="event-column-actions" aria-label={t("actionsLabel")}>
                  {heading && !masterList ? t("actionsLabel") : null}
                  {allowCreate && !heading && !masterList && (
                  <button
                    type="button"
                    className="button-ghost button-icon"
                    title={t("addRowTitle")}
                    aria-label={t("addRowTitle")}
                    disabled={showNewRow || creatingNewRow}
                    onClick={() => {
                      setShowNewRow(true);
                      setNewRowDraft(createNewRowDraft(definition));
                    }}
                  >
                    +
                  </button>
                  )}
                </th>
              ) : null}
            </tr>
          </thead>
          <tbody>
            {showNewRow ? (
              <tr className="event-row-new">
                {columns.map((column) => (
                  <td key={column.id}>
                    {renderEditableCell(null, column.id, column.value_type, newRowDraft[column.id] ?? emptyValueForType(column.value_type), {
                      isNewRow: true,
                      disabled: creatingNewRow,
                    })}
                  </td>
                ))}
                {editable ? (
                  <td>
                    <div className="event-row-actions">
                      <button
                        type="button"
                        className="button-ghost button-icon button-icon-danger"
                        title={t("discardNewRowTitle")}
                        aria-label={t("discardNewRowTitle")}
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
              activeGroupBy && !editable ? (
                groupedDisplayRows.map((row) => (
                  <tr key={`structured-list-grouped-${row.key}`} className="structured-list-grouped-row">
                    {row.cells.map((cell, index) => <td key={columns[index].id}>{cell}</td>)}
                  </tr>
                ))
              ) : (
                (activeGroupBy
                  ? groupedEntries
                  : [{ key: "__all__", label: "", entries: sortedEntries }]
                ).map((group) => (
                  <Fragment key={`structured-list-group-${group.key}`}>
                    {activeGroupBy ? (
                      <tr className="structured-list-group-row">
                        <td colSpan={columns.length + (editable ? 1 : 0)}>{group.label}</td>
                      </tr>
                    ) : null}
                    {group.entries.map((entry) => {
                      const trackedInfo = entryTrackedStatusById?.[entry.id];
                      // A removed row is a phantom reconstructed from its last-known
                      // values (see list_snapshot_service._merge_tracked_list_entries) -
                      // it no longer exists in the shared list, so it's always struck
                      // through and non-interactive regardless of the editable prop.
                      if (trackedInfo?.status === "removed") {
                        return (
                          <tr key={entry.id} className="tracked-removed-row">
                            {columns.map((column, index) => (
                              <td key={column.id}>
                                <span className="tracked-strike">{renderValueSummary(column.value_type, rowValue(entry, column.id))}</span>
                                {index === columns.length - 1 && onAcceptTrackedEntry && (
                                  <TrackedChangeHideButton
                                    title={t("hideRemovedEntryTitle")}
                                    onAccept={() => onAcceptTrackedEntry(entry.id)}
                                  />
                                )}
                              </td>
                            ))}
                            {editable ? <td /> : null}
                          </tr>
                        );
                      }
                      return (
                        <tr key={entry.id}>
                          {columns.map((column) => {
                            const value = rowValue(entry, column.id);
                            const changed = trackedInfo?.status === "changed" && !valuesEqual(value, trackedInfo.before?.[column.id]);
                            const added = trackedInfo?.status === "added";
                            return (
                              <td key={column.id} className={changed || added ? "tracked-cell" : undefined}>
                                {changed && (
                                  <div className="tracked-before-caption tracked-strike">
                                    {valueSummary(column.value_type, trackedInfo?.before?.[column.id] ?? {}, participantNames, sortedEvents, t)}
                                  </div>
                                )}
                                {editable
                                  ? renderEditableCell(entry.id, column.id, column.value_type, value, { isNewRow: false })
                                  : (changed || added
                                      ? <span className="tracked-underline">{renderValueSummary(column.value_type, value)}</span>
                                      : renderValueSummary(column.value_type, value))}
                                {(changed || added) && onAcceptTrackedEntry && (
                                  <TrackedChangeHideButton onAccept={() => onAcceptTrackedEntry(entry.id)} />
                                )}
                              </td>
                            );
                          })}
                          {editable ? (
                            <td>
                              <div className="event-row-actions">
                                <button
                                  type="button"
                                  className={masterList ? "button-icon-soft button-icon-soft-danger" : heading ? "button-secondary button-danger" : "button-ghost button-icon button-icon-danger"}
                                  title={t("deleteRowTitle")}
                                  aria-label={t("deleteRowTitle")}
                                  onClick={() => void onDeleteEntry(entry.id)}
                                >
                                  {masterList ? <ActionIcon name="delete" /> : heading ? t("deleteButton") : "x"}
                                </button>
                              </div>
                            </td>
                          ) : null}
                        </tr>
                      );
                    })}
                  </Fragment>
                ))
              )
            ) : !showNewRow ? (
              <tr>
                <td colSpan={columns.length + (editable ? 1 : 0)}>
                  <span className="muted">{resolvedEmptyMessage}</span>
                </td>
              </tr>
            ) : null}
          </tbody>
          {masterList && editable && allowCreate && <tfoot><tr><td colSpan={columns.length + 1}><button type="button" className="button-ghost list-manager-add-row" disabled={showNewRow || creatingNewRow} onClick={() => { setShowNewRow(true); setNewRowDraft(createNewRowDraft(definition)); }}>{listT("addEntry")}</button></td></tr></tfoot>}
        </table>
      </div>

      <Modal
        open={Boolean(participantPicker)}
        onClose={() => {
          setParticipantPicker(null);
          setParticipantSearch("");
        }}
        title={t("participantPickerTitle")}
        description={t("participantPickerDescription")}
      >
        <div className="grid">
          <label className="field-stack">
            <span className="field-label">{t("search")}</span>
            <input
              value={participantSearch}
              onChange={(event) => setParticipantSearch(event.target.value)}
              placeholder={t("participantFilterPlaceholder")}
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
                    onChange={() => toggleParticipantPickerSelection(participant.id)}
                  />
                  <span>{participant.display_name}</span>
                </label>
              );
            })}
          </div>
        </div>
      </Modal>
    </>
  );
}
