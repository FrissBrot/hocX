"use client";

// Gemeinsamer Zeilen-Inspektor für Tabelle (Typ 6) und Matrix (Typ 11). Vorher hatten beide
// eigene Designer mit abweichenden Zeilentypen, Schaltern («Gesperrt» als Checkbox bzw.
// Switch) und Verhalten beim Typwechsel (die Tabelle behielt die alte row_config).
import { useTranslations } from "next-intl";

import { useParticipantSelectable } from "@/contexts/participant-date-context";
import { SearchableMultiSelect, SearchableSelect } from "@/components/ui/searchable-select";
import { elementTypeLabels } from "@/lib/constants/element-types";
import { normalizeEventFilter, type EventFilter } from "@/lib/element-types/event-filter";
import { embeddableElementTypes } from "@/lib/element-types/registry";
import type { TagConfig } from "@/lib/hooks/use-tag-config";
import { formatDateRange } from "@/lib/utils/format";
import type { EventSummary, ParticipantSummary, StructuredListDefinition, StructuredListEntry } from "@/types/api";

import { defaultRowConfig, EVENT_DISPLAY_DEFAULTS, type EventDisplayKey, isSimpleRowType, rowTypeAllowed, SIMPLE_ROW_TYPES, type TableRow } from "./block-form";
import { EventFilterEditor } from "./event-filter-editor";

type TFunc = (key: string, values?: Record<string, string | number>) => string;

export const AUTO_SOURCE_FIELDS: Record<"participants" | "events" | "list", string[]> = {
  participants: ["display_name", "first_name", "last_name", "email"],
  events: ["title", "event_date", "tag", "participant_count"],
  list: ["column_one", "column_two"],
};

export function rowTypeLabel(rowType: string, t: TFunc, tTypes: TFunc): string {
  if (isSimpleRowType(rowType)) return t(`rowType.${rowType}`);
  return elementTypeLabels(tTypes)[Number(rowType)] ?? t("rowType.unknown");
}

export function listEntryText(entry: StructuredListEntry, definition: StructuredListDefinition | null, describe: (value: Record<string, unknown> | null | undefined, valueType: string) => string, fallback: string) {
  if (!definition) return fallback;
  const one = describe(entry.column_one_value as Record<string, unknown>, definition.column_one_value_type);
  const two = describe(entry.column_two_value as Record<string, unknown>, definition.column_two_value_type);
  return [one, two].filter(Boolean).join(" – ") || fallback;
}

export type RowInspectorData = {
  participants: ParticipantSummary[];
  events: EventSummary[];
  lists: StructuredListDefinition[];
  listEntries: Record<string, StructuredListEntry[]>;
  ensureListEntries: (listId: string) => void;
  knownEventTags: string[];
  tagConfig: TagConfig;
};

export function useListValueDescriber(participants: ParticipantSummary[], events: EventSummary[]) {
  return (value: Record<string, unknown> | null | undefined, valueType: string): string => {
    if (!value) return "";
    if (valueType === "participant") {
      return participants.find((participant) => participant.id === value.participant_id)?.display_name ?? "";
    }
    if (valueType === "participants") {
      const ids = Array.isArray(value.participant_ids) ? (value.participant_ids as string[]) : [];
      return participants.filter((participant) => ids.includes(participant.id)).map((participant) => participant.display_name).join(", ");
    }
    if (valueType === "event") {
      const event = events.find((entry) => entry.id === value.event_id);
      return event ? `${formatDateRange(event.event_date, event.event_end_date)} · ${event.title}` : "";
    }
    return String(value.text_value ?? "").trim();
  };
}

export function RowInspector({
  row,
  kind,
  autoSource,
  data,
  onChange,
  onRemove,
  heading,
}: {
  row: TableRow;
  kind: "form" | "matrix";
  /** Quelle der automatischen Matrixspalten (für den Platzhalter der Zeile). */
  autoSource: "participants" | "events" | "list" | null;
  data: RowInspectorData;
  onChange: (next: TableRow) => void;
  onRemove: () => void;
  heading: string;
}) {
  const t = useTranslations("templates.elementEditor");
  const tTypes = useTranslations("templates");
  const isParticipantSelectable = useParticipantSelectable();
  const describeValue = useListValueDescriber(data.participants, data.events);
  const patch = (next: Partial<TableRow>) => onChange({ ...row, ...next });
  const patchConfig = (next: Record<string, unknown>) => patch({ row_config: { ...row.row_config, ...next } });
  const simpleTypes = SIMPLE_ROW_TYPES.filter((type) => rowTypeAllowed(kind, type));
  const embeddedTypes = embeddableElementTypes().filter((type) => rowTypeAllowed(kind, String(type.id)));
  const typeLabels = elementTypeLabels(tTypes);
  const sortedEvents = [...data.events].sort((left, right) => left.event_date.localeCompare(right.event_date));
  const eventLabel = (event: EventSummary) => `${formatDateRange(event.event_date, event.event_end_date)} · ${event.title}`;

  function changeRowType(nextType: string) {
    // Typwechsel setzt die Zeilen-Konfiguration zurück - bei Tabelle und Matrix gleich.
    patch({ row_type: nextType, row_config: defaultRowConfig(nextType) });
  }

  const eventFilter = normalizeEventFilter(row.row_config.event_filter, "future");
  const setEventFilter = (next: EventFilter) => patchConfig({ event_filter: next });

  return (
    <div className="matrix-designer-inspector">
      <div className="matrix-designer-inspector-header">
        <div>
          <div className="eyebrow">{heading}</div>
          <div className="matrix-designer-inspector-title">{row.label || t("row.unnamed")}</div>
        </div>
        <button type="button" className="button-ghost button-danger" onClick={onRemove}>
          {t("remove")}
        </button>
      </div>

      <label className="field-stack">
        <span className="field-label">{row.row_type === "list_entry" ? t("row.aliasLabel") : t("row.label")}</span>
        <input
          value={row.label}
          onChange={(event) => patch({ label: event.target.value })}
          placeholder={row.row_type === "list_entry" ? t("row.aliasPlaceholder") : t("row.labelPlaceholder")}
        />
      </label>

      <label className="field-stack">
        <span className="field-label">{t("row.type")}</span>
        <select value={row.row_type} onChange={(event) => changeRowType(event.target.value)}>
          <optgroup label={t("row.simpleTypes")}>
            {simpleTypes.map((type) => (
              <option key={type} value={type}>{t(`rowType.${type}`)}</option>
            ))}
          </optgroup>
          {embeddedTypes.length ? (
            <optgroup label={t("row.embeddedTypes")}>
              {embeddedTypes.map((type) => (
                <option key={type.id} value={String(type.id)}>{typeLabels[type.id]}</option>
              ))}
            </optgroup>
          ) : null}
        </select>
        <span className="field-help">
          {isSimpleRowType(row.row_type) ? t(`rowTypeHelp.${row.row_type}`) : t("rowTypeHelp.embedded", { type: typeLabels[Number(row.row_type)] ?? "" })}
        </span>
      </label>

      <label className="matrix-designer-switch-row">
        <input
          type="checkbox"
          className="mini-menu-switch-input"
          checked={row.locked_in_protocol}
          onChange={(event) => patch({ locked_in_protocol: event.target.checked })}
        />
        <span className="mini-menu-switch" aria-hidden="true" />
        <span>{t("row.locked")}</span>
      </label>

      {row.row_type === "text" ? (
        <label className="field-stack">
          <span className="field-label">{t("row.initialText")}</span>
          <input
            value={row.template_value}
            onChange={(event) => patch({ template_value: event.target.value })}
            placeholder={t("row.initialTextPlaceholder", { title: "{title}" })} // i18n-ok: Platzhalter-Token, kein UI-Text
          />
        </label>
      ) : null}

      {row.row_type === "participant" ? (
        <label className="field-stack">
          <span className="field-label">{t("row.initialParticipant")}</span>
          <SearchableSelect
            options={data.participants}
            isOptionSelectable={isParticipantSelectable}
            getId={(participant) => participant.id}
            getLabel={(participant) => participant.display_name}
            value={row.template_participant_id}
            onChange={(participant) => patch({ template_participant_id: participant?.id ?? null })}
            nullLabel={t("row.noDefault")}
          />
        </label>
      ) : null}

      {row.row_type === "participants" ? (
        <label className="field-stack">
          <span className="field-label">{t("row.initialParticipants")}</span>
          <SearchableMultiSelect
            options={data.participants}
            isOptionSelectable={isParticipantSelectable}
            getId={(participant) => participant.id}
            getLabel={(participant) => participant.display_name}
            values={row.template_participant_ids}
            onChange={(ids) => patch({ template_participant_ids: ids })}
            emptySelectionLabel={t("row.noDefault")}
          />
        </label>
      ) : null}

      {row.row_type === "event" ? (
        <label className="field-stack">
          <span className="field-label">{t("row.initialEvent")}</span>
          <SearchableSelect
            options={sortedEvents}
            getId={(event) => event.id}
            getLabel={eventLabel}
            value={row.template_event_id}
            onChange={(event) => patch({ template_event_id: event?.id ?? null })}
            nullLabel={t("row.noDefault")}
          />
        </label>
      ) : null}

      {row.row_type === "list_entry" ? (() => {
        const listId = typeof row.row_config.linked_list_id === "string" ? row.row_config.linked_list_id : null;
        const definition = data.lists.find((list) => list.id === listId) ?? null;
        const entries = listId ? data.listEntries[listId] ?? [] : [];
        const fixed = row.row_config.list_fixed_column === "column_two" ? "column_two" : "column_one";
        return (
          <div className="field-stack">
            <label className="field-stack">
              <span className="field-label">{t("row.list")}</span>
              <SearchableSelect
                options={data.lists}
                getId={(list) => list.id}
                getLabel={(list) => list.name}
                value={listId}
                onChange={(list) => {
                  if (list) data.ensureListEntries(list.id);
                  patchConfig({ linked_list_id: list?.id ?? null, linked_list_entry_id: null });
                }}
                nullLabel={t("row.chooseList")}
              />
            </label>
            {listId ? (
              <>
                <label className="field-stack">
                  <span className="field-label">{t("row.listEntry")}</span>
                  <SearchableSelect
                    options={entries}
                    getId={(entry) => entry.id}
                    getLabel={(entry) => listEntryText(entry, definition, describeValue, t("row.emptyEntry"))}
                    value={typeof row.row_config.linked_list_entry_id === "string" ? row.row_config.linked_list_entry_id : null}
                    onChange={(entry) => patchConfig({ linked_list_entry_id: entry?.id ?? null })}
                    nullLabel={t("row.chooseEntry")}
                  />
                </label>
                <label className="field-stack">
                  <span className="field-label">{t("row.fixedColumn")}</span>
                  <select value={fixed} onChange={(event) => patchConfig({ list_fixed_column: event.target.value })}>
                    <option value="column_one">{t("row.fixedColumnOption", { column: definition?.column_one_title || t("row.columnOne") })}</option>
                    <option value="column_two">{t("row.fixedColumnOption", { column: definition?.column_two_title || t("row.columnTwo") })}</option>
                  </select>
                </label>
                <label className="checkbox-row">
                  <input
                    type="checkbox"
                    checked={row.row_config.value_source === "historical"}
                    onChange={(event) => patchConfig({ value_source: event.target.checked ? "historical" : "live" })}
                  />
                  {t("row.historical")}
                </label>
                <span className="field-help">{t("row.historicalHelp")}</span>
              </>
            ) : null}
          </div>
        );
      })() : null}

      {row.row_type === "events" || row.row_type === "7" ? (
        <div className="matrix-designer-inspector-section">
          <div className="eyebrow">{t("row.filterEvents")}</div>
          <EventFilterEditor
            value={eventFilter}
            onChange={setEventFilter}
            knownEventTags={data.knownEventTags}
            tagConfig={data.tagConfig}
            rangeModes={["future", "past", "all", "window"]}
            showColumnFilter={kind === "matrix"}
            showSortLimit
          />
        </div>
      ) : null}

      {row.row_type === "7" ? (
        <div className="field-stack">
          <span className="field-label">{t("row.displayedFields")}</span>
          <EventDisplayChips config={row.row_config} onChange={patchConfig} />
        </div>
      ) : null}

      {kind === "matrix" && autoSource ? (
        <div className="matrix-designer-inspector-section">
          <div className="eyebrow">{t("row.autoValueHeading")}</div>
          <label className="field-stack">
            <span className="field-label">{t(`row.autoValueFrom.${autoSource}`)}</span>
            <select value={row.auto_source_field ?? ""} onChange={(event) => patch({ auto_source_field: event.target.value || null })}>
              <option value="">{t("row.noAutoValue")}</option>
              {AUTO_SOURCE_FIELDS[autoSource].map((field) => (
                <option key={field} value={field}>{t(`autoField.${field}`)}</option>
              ))}
            </select>
            <span className="field-help">{t("row.autoValueHelp")}</span>
          </label>
        </div>
      ) : null}
    </div>
  );
}

const DISPLAY_CHIPS: EventDisplayKey[] = [
  "event_show_date",
  "event_show_tag",
  "event_show_tag_colors",
  "event_show_title",
  "event_show_description",
  "event_show_participant_count",
  "event_show_cancelled",
];

/** Spalten/Felder einer Terminliste - gleiche Auswahl für Terminliste und eingebettete Liste. */
export function EventDisplayChips({ config, onChange }: { config: Record<string, unknown>; onChange: (patch: Record<string, unknown>) => void }) {  // i18n-ok: TS-Signatur, kein UI-Text
  const t = useTranslations("templates.elementEditor");
  return (
    <div className="matrix-designer-chips">
      {DISPLAY_CHIPS.map((key) => {
        const on = typeof config[key] === "boolean" ? (config[key] as boolean) : EVENT_DISPLAY_DEFAULTS[key];
        return (
          <button
            key={key}
            type="button"
            aria-pressed={on}
            className={`matrix-designer-chip${on ? " matrix-designer-chip-active" : ""}`}
            onClick={() => onChange({ [key]: !on })}
          >
            {t(`display.${key}`)}
          </button>
        );
      })}
    </div>
  );
}
