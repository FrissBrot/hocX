"use client";

// Ein Baustein für «welche Termine?» an allen Stellen des Element-Editors: Wiederholung pro
// Termin, Terminliste, Sitzungsdatum, Matrix-Automodus, Matrix-Terminzeile und eingebettete
// Terminliste. Vorher hatte jede Stelle eigene Felder mit eigener Logik (siehe
// lib/element-types/event-filter.ts für Speicherformat und Auswertung).
import { useId, useState } from "react";
import { useTranslations } from "next-intl";

import { SearchableSelect } from "@/components/ui/searchable-select";
import { TagInput } from "@/components/ui/tag-input";
import { type EventFilter, type EventRangeMode, splitTags } from "@/lib/element-types/event-filter";
import type { TagConfig } from "@/lib/hooks/use-tag-config";
import type { CycleConfigSummary } from "@/types/api";
import { Select } from "@/components/ui/select";

export const CYCLE_OFFSETS = [-2, -1, 0, 1] as const;

type TFunc = (key: string, values?: Record<string, string | number>) => string;

export function cycleOffsetText(offset: number, t: TFunc) {
  if (offset === 0) return t("cycle.current");
  if (offset === -1) return t("cycle.previous");
  if (offset === 1) return t("cycle.next");
  return t("cycle.relative", { offset });
}

export function DayStepper({ value, onChange, label, min = -3650 }: { value: number; onChange: (value: number) => void; label: string; min?: number }) {
  const t = useTranslations("templates.elementEditor");
  return (
    <span className="event-window-stepper">
      <button type="button" className="button-icon-soft" aria-label={t("stepperDecrease", { label })} onClick={() => onChange(Math.max(min, value - 1))}>−</button>
      <span className="event-window-stepper-value" aria-label={label}>{value}</span>
      <button type="button" className="button-icon-soft" aria-label={t("stepperIncrease", { label })} onClick={() => onChange(value + 1)}>+</button>
    </span>
  );
}

export type EventFilterEditorProps = {
  value: EventFilter;
  onChange: (next: EventFilter) => void;
  knownEventTags: string[];
  tagConfig: TagConfig;
  /** Angebotene Zeiträume, in dieser Reihenfolge. Leer = kein Zeitraum (nur Tag/Titel). */
  rangeModes: EventRangeMode[];
  showTitle?: boolean;
  showDescription?: boolean;
  showCycle?: boolean;
  /** Mit Liste: statt nur «Zyklus der Vorlage» auch einen anderen Zyklus wählbar. */
  cycleConfigs?: CycleConfigSummary[];
  showColumnFilter?: boolean;
  showSortLimit?: boolean;
  tagLabel?: string;
};

export function EventFilterEditor({
  value,
  onChange,
  knownEventTags,
  tagConfig,
  rangeModes,
  showTitle = true,
  showDescription = true,
  showCycle = true,
  cycleConfigs,
  showColumnFilter = false,
  showSortLimit = false,
  tagLabel,
}: EventFilterEditorProps) {
  const t = useTranslations("templates.elementEditor");
  const id = useId();
  const hasAdvanced = showDescription || showSortLimit;
  const [advancedOpen, setAdvancedOpen] = useState(
    Boolean(value.description) || value.sort === "desc" || value.limit !== null
  );
  const patch = (next: Partial<EventFilter>) => onChange({ ...value, ...next });
  const setRange = (next: Partial<EventFilter["range"]>) => patch({ range: { ...value.range, ...next } });

  return (
    <div className="event-filter-editor">
      <div className={showTitle ? "two-col" : undefined}>
        <label className="field-stack">
          <span className="field-label">{tagLabel ?? t("filter.tags")}</span>
          {/* Ohne Tag-Umbenennen/-Farbe: ein Filter soll keine globalen Tags ändern. */}
          <TagInput
            value={value.tags.join(", ")}
            onChange={(text) => patch({ tags: splitTags(text) })}
            suggestions={knownEventTags}
            tagConfig={tagConfig}
            placeholder={t("filter.tagsPlaceholder")}
          />
          <span className="field-help">{t("filter.tagsHelp")}</span>
        </label>
        {showTitle ? (
          <label className="field-stack">
            <span className="field-label">{t("filter.title")}</span>
            <input value={value.title} onChange={(event) => patch({ title: event.target.value })} placeholder={t("filter.containsPlaceholder")} />
          </label>
        ) : null}
      </div>

      {rangeModes.length ? (
        <div className="field-stack">
          <label className="field-label" htmlFor={`${id}-range`}>{t("filter.range")}</label>
          <Select id={`${id}-range`} value={value.range.mode} onChange={(event) => setRange({ mode: event.target.value as EventRangeMode })}>
            {rangeModes.map((mode) => (
              <option key={mode} value={mode}>{t(`filter.rangeMode.${mode}`)}</option>
            ))}
          </Select>
          {value.range.mode === "window" ? (
            <div className="event-window-box">
              <div className="event-window-row">
                <span>{t("filter.windowFrom")}</span>
                <DayStepper
                  value={Math.max(0, -value.range.start_days)}
                  min={0}
                  label={t("filter.daysBefore")}
                  onChange={(days) => setRange({ start_days: -days })}
                />
                <span>{t("filter.windowDaysBefore")}</span>
                <DayStepper
                  value={value.range.end_days}
                  label={t("filter.daysAfter")}
                  onChange={(days) => setRange({ end_days: days })}
                />
                <span>{t("filter.windowDaysAfter")}</span>
              </div>
              <span className="field-help">{t("filter.windowHelp")}</span>
            </div>
          ) : null}
        </div>
      ) : null}

      {showCycle ? (
        <div className={cycleConfigs ? "two-col" : undefined}>
          <label className="field-stack">
            <span className="field-label">{t("filter.cycle")}</span>
            <Select
              value={value.cycle ? String(value.cycle.offset) : ""}
              onChange={(event) =>
                patch({ cycle: event.target.value === "" ? null : { config_id: value.cycle?.config_id ?? null, offset: Number(event.target.value) } })
              }
            >
              <option value="">{t("cycle.none")}</option>
              {CYCLE_OFFSETS.map((offset) => (
                <option key={offset} value={offset}>{cycleOffsetText(offset, t)}</option>
              ))}
            </Select>
            <span className="field-help">{t("filter.cycleHelp")}</span>
          </label>
          {cycleConfigs && value.cycle ? (
            <label className="field-stack">
              <span className="field-label">{t("filter.cycleConfig")}</span>
              <SearchableSelect
                options={cycleConfigs}
                getId={(config) => config.id}
                getLabel={(config) => config.name}
                value={value.cycle.config_id}
                onChange={(config) => patch({ cycle: { offset: value.cycle?.offset ?? 0, config_id: config?.id ?? null } })}
                nullLabel={t("cycle.template")}
              />
            </label>
          ) : null}
        </div>
      ) : null}

      {showColumnFilter ? (
        <label className="checkbox-row">
          <input type="checkbox" checked={value.use_column_filter} onChange={(event) => patch({ use_column_filter: event.target.checked })} />
          {t("filter.useColumnFilter")}
        </label>
      ) : null}

      {hasAdvanced ? (
        <div className="event-filter-advanced">
          <button
            type="button"
            className="button-ghost event-filter-advanced-toggle"
            aria-expanded={advancedOpen}
            onClick={() => setAdvancedOpen((current) => !current)}
          >
            {advancedOpen ? t("advancedHide") : t("advancedShow")}
          </button>
          {advancedOpen ? (
            <div className="two-col">
              {showDescription ? (
                <label className="field-stack">
                  <span className="field-label">{t("filter.description")}</span>
                  <input value={value.description} onChange={(event) => patch({ description: event.target.value })} placeholder={t("filter.containsPlaceholder")} />
                </label>
              ) : null}
              {showSortLimit ? (
                <>
                  <label className="field-stack">
                    <span className="field-label">{t("filter.sort")}</span>
                    <Select value={value.sort} onChange={(event) => patch({ sort: event.target.value === "desc" ? "desc" : "asc" })}>
                      <option value="asc">{t("filter.sortAsc")}</option>
                      <option value="desc">{t("filter.sortDesc")}</option>
                    </Select>
                  </label>
                  <label className="field-stack">
                    <span className="field-label">{t("filter.limit")}</span>
                    <input
                      type="number"
                      min={1}
                      max={500}
                      value={value.limit ?? ""}
                      placeholder={t("filter.limitPlaceholder")}
                      onChange={(event) => {
                        const parsed = Number(event.target.value);
                        patch({ limit: event.target.value && parsed > 0 ? Math.min(500, Math.trunc(parsed)) : null });
                      }}
                    />
                  </label>
                </>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
