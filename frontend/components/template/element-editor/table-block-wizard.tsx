"use client";

// Assistent beim Anlegen eines Tabellenblocks: wenige grosse Entscheidungen (Wie oft? Welche Termine
// bzw. Pendenzen? Woher die Zeilen? Womit starten?), danach die Detailseiten des Block-Editors.
// Jede Wahl ändert sofort das Formular (die Vorschau rechts zeigt das Ergebnis); «Überspringen»
// geht jederzeit direkt zu den Details.
import { type ReactNode, useState } from "react";
import { useTranslations } from "next-intl";

import { type BlockForm, defaultRow, setRepeatSource, repeatEventFilter, type TableRow } from "./block-form";
import type { RowInspectorData } from "./row-inspector";
import { eventFieldsOf, todoFieldsOf } from "./table-block-editor";

type Repeat = "none" | "event" | "todo";
type StepKey = "repeat" | "filter" | "source" | "preset";
type PresetKey = "event_overview" | "event_costs" | "todo_status" | "responsibilities" | "empty";

/** Startvorlagen: Felder aus Termin bzw. Pendenz (mit Bezeichnung) und eigene Zeilen. */
const PRESETS: Array<{
  key: PresetKey;
  repeat: Repeat[];
  eventFields?: Record<string, string>;
  todoFields?: string[];
  rows: Array<[string, string]>;
}> = [
  { key: "event_overview", repeat: ["event"], eventFields: { event_date: "when", location: "where", organizer_ids: "" }, rows: [["whoGoes", "participants"], ["meetingPoint", "text"], ["program", "text"]] },
  { key: "event_costs", repeat: ["event"], eventFields: { event_date: "date", spezial_text1: "", spezial_text2: "" }, rows: [["registrationUntil", "text"], ["responsible", "participant"]] },
  { key: "todo_status", repeat: ["todo"], todoFields: ["participant", "due_date", "status"], rows: [["status", "text"], ["nextStep", "text"]] },
  { key: "responsibilities", repeat: ["none", "event", "todo"], rows: [["responsible", "participant"], ["deputy", "participant"], ["remark", "text"]] },
  { key: "empty", repeat: ["none", "event", "todo"], rows: [["", "text"]] },
];

const DEFAULT_PRESET: Record<Repeat, PresetKey> = { none: "responsibilities", event: "event_overview", todo: "todo_status" };

export function TableBlockWizard({
  form,
  onChange,
  data,
  allowedRepeat,
  matchingCount,
  onDone,
  preview,
}: {
  form: BlockForm;
  onChange: (next: BlockForm) => void;
  data: RowInspectorData;
  allowedRepeat: Array<"event" | "todo">;
  /** Passende Termine bzw. Pendenzen (Vorschau), für «Aktuell n Termine → n Blöcke». */
  matchingCount: number;
  onDone: () => void;
  preview: ReactNode;
}) {
  const t = useTranslations("templates.elementEditor");
  const [step, setStep] = useState(0);
  const repeat = String(form.config.repeat_source ?? "none") as Repeat;
  const [preset, setPreset] = useState<PresetKey>(DEFAULT_PRESET[repeat]);
  const manual = !form.config.linked_list_id;
  const steps: StepKey[] = ["repeat", ...(repeat !== "none" ? (["filter"] as StepKey[]) : []), "source", ...(manual ? (["preset"] as StepKey[]) : [])];
  const current = steps[Math.min(step, steps.length - 1)];
  const index = steps.indexOf(current);
  const setConfig = (next: Record<string, unknown>) => onChange({ ...form, config: { ...form.config, ...next } });
  const filter = repeatEventFilter(form);
  const setFilter = (next: Partial<typeof filter>) => setConfig({ repeat_event_filter: { ...filter, ...next } });

  function applyPreset(key: PresetKey, base: BlockForm = form) {
    const definition = PRESETS.find((item) => item.key === key);
    if (!definition) return;
    setPreset(key);
    const rows: TableRow[] = definition.rows.map(([label, rowType], position) => ({
      ...defaultRow(String(position + 1)),
      label: label ? t(`wizard.presetRow.${label}`) : "",
      row_type: rowType,
    }));
    const config: Record<string, unknown> = { ...base.config, rows };
    if (definition.eventFields) {
      const wanted = definition.eventFields;
      config.event_fields = eventFieldsOf(base).map((field) => ({
        ...field,
        enabled: field.field in wanted,
        label: wanted[field.field] ? t(`wizard.presetField.${wanted[field.field]}`) : "",
      }));
    }
    if (definition.todoFields) {
      const wanted = definition.todoFields;
      config.todo_fields = todoFieldsOf(base).map((field) => ({ ...field, enabled: wanted.includes(field.field), label: "" }));
    }
    onChange({ ...base, config });
  }

  function chooseRepeat(next: Repeat) {
    onChange(setRepeatSource(form, next));
    setPreset(DEFAULT_PRESET[next]);
  }

  function finish(applySelected: boolean) {
    if (applySelected && manual) applyPreset(preset);
    onDone();
  }

  const card = (active: boolean) => `rule-option-card table-wizard-card${active ? " rule-option-card-active" : ""}`;
  const isLast = index >= steps.length - 1;

  return (
    <div className="element-create-layout table-wizard">
      <div className="element-create-fields table-wizard-main">
        <ol className="table-wizard-steps">
          {steps.map((key, position) => {
            const done = position < index;
            const active = position === index;
            return (
              <li key={key}>
                <button
                  type="button"
                  className={`table-wizard-step${active ? " table-wizard-step-active" : ""}${done ? " table-wizard-step-done" : ""}`}
                  aria-current={active ? "step" : undefined}
                  disabled={position > index}
                  onClick={() => setStep(position)}
                >
                  <span className="table-wizard-step-number" aria-hidden="true">{done ? "✓" : position + 1}</span>
                  <span>{t(`wizard.step.${key === "filter" ? `filter_${repeat}` : key}`)}</span>
                </button>
              </li>
            );
          })}
        </ol>

        <div className="table-wizard-head">
          <h3>{t(`wizard.title.${current === "filter" ? `filter_${repeat}` : current}`)}</h3>
          <p className="muted">{t(`wizard.description.${current === "filter" ? `filter_${repeat}` : current}`)}</p>
        </div>

        {current === "repeat" ? (
          <div className="table-wizard-grid">
            {(["none", ...allowedRepeat] as Repeat[]).map((option) => (
              <button key={option} type="button" className={card(repeat === option)} aria-pressed={repeat === option} onClick={() => chooseRepeat(option)}>
                <strong>{t(`repeat.option.${option}`)}</strong>
                <span className="muted">{t(`repeat.optionHelp.${option}`)}</span>
                <span className="field-help table-wizard-example">{t(`wizard.example.${option}`)}</span>
              </button>
            ))}
          </div>
        ) : null}

        {current === "filter" && repeat === "event" ? (
          <div className="table-wizard-section">
            <div className="field-stack">
              <span className="field-label">{t("wizard.whichTag")}</span>
              <div className="table-wizard-chips">
                {data.knownEventTags.map((tag) => {
                  const on = filter.tags.some((entry) => entry.toLowerCase() === tag.toLowerCase());
                  const color = data.tagConfig[tag]?.color;
                  return (
                    <button
                      key={tag}
                      type="button"
                      aria-pressed={on}
                      className={`matrix-designer-chip table-wizard-tag${on ? " matrix-designer-chip-active" : ""}`}
                      onClick={() => setFilter({ tags: on ? filter.tags.filter((entry) => entry.toLowerCase() !== tag.toLowerCase()) : [...filter.tags, tag] })}
                    >
                      {/* Tag-Farbe ist eine Laufzeitfarbe des Mandanten */}
                      <span className="table-wizard-tag-dot" style={color ? { background: color } : undefined} aria-hidden="true" />
                      {tag}
                    </button>
                  );
                })}
              </div>
              <span className="field-help">{t("wizard.tagHelp")}</span>
            </div>
            <div className="field-stack">
              <span className="field-label">{t("wizard.whichRange")}</span>
              <div className="table-wizard-grid">
                {(["window", "future", "past", "all"] as const).map((mode) => (
                  <button key={mode} type="button" className={card(filter.range.mode === mode)} aria-pressed={filter.range.mode === mode} onClick={() => setFilter({ range: { ...filter.range, mode } })}>
                    <strong>{t(`wizard.range.${mode}`)}</strong>
                    <span className="muted">{t(`wizard.rangeHelp.${mode}`, { start: filter.range.start_days, end: filter.range.end_days })}</span>
                  </button>
                ))}
              </div>
            </div>
            <p className={matchingCount ? "table-wizard-match" : "table-wizard-match table-wizard-match-none"}>
              {matchingCount ? t("repeat.matchSummary", { count: matchingCount }) : t("repeat.matchNone")} · {t("wizard.refineLater")}
            </p>
          </div>
        ) : null}

        {current === "filter" && repeat === "todo" ? (
          <div className="table-wizard-grid">
            {[true, false].map((openOnly) => {
              const active = (form.config.todo_open_only !== false) === openOnly;
              return (
                <button key={String(openOnly)} type="button" className={card(active)} aria-pressed={active} onClick={() => setConfig({ todo_open_only: openOnly })}>
                  <strong>{t(openOnly ? "wizard.todoOpen" : "wizard.todoAll")}</strong>
                  <span className="muted">{t(openOnly ? "wizard.todoOpenHelp" : "wizard.todoAllHelp")}</span>
                </button>
              );
            })}
          </div>
        ) : null}

        {current === "source" ? (
          <div className="table-wizard-section">
            <div className="table-wizard-grid">
              <button type="button" className={card(manual)} aria-pressed={manual} onClick={() => setConfig({ linked_list_id: null })}>
                <strong>{t("tableBlock.source.manual")}</strong>
                <span className="muted">{t(repeat === "none" ? "wizard.sourceManualHelp" : `wizard.sourceManualHelpWith.${repeat}`)}</span>
              </button>
              <button
                type="button"
                className={card(!manual)}
                aria-pressed={!manual}
                disabled={data.lists.length === 0}
                onClick={() => setConfig({ linked_list_id: data.lists[0]?.id ?? null })}
              >
                <strong>{t("tableBlock.source.list")}</strong>
                <span className="muted">{data.lists.length ? t("wizard.sourceListHelp") : t("tableBlock.noLists")}</span>
              </button>
            </div>
            {!manual ? (
              <div className="field-stack">
                <span className="field-label">{t("wizard.whichList")}</span>
                <div className="table-wizard-grid">
                  {data.lists.map((list) => (
                    <button key={list.id} type="button" className={card(list.id === form.config.linked_list_id)} aria-pressed={list.id === form.config.linked_list_id} onClick={() => setConfig({ linked_list_id: list.id })}>
                      <strong>{list.name}</strong>
                      <span className="muted">{`${list.column_one_title} · ${list.column_two_title}`}</span>
                    </button>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        ) : null}

        {current === "preset" ? (
          <div className="table-wizard-grid">
            {PRESETS.filter((item) => item.repeat.includes(repeat)).map((item) => {
              const fieldChips = item.eventFields
                ? Object.entries(item.eventFields).map(([field, label]) => (label ? t(`wizard.presetField.${label}`) : t(`eventField.${field}`)))
                : (item.todoFields ?? []).map((field) => t(`todoField.${field}`));
              return (
                <button key={item.key} type="button" className={card(preset === item.key)} aria-pressed={preset === item.key} onClick={() => applyPreset(item.key)}>
                  <strong>{t(`wizard.preset.${item.key}.title`)}</strong>
                  <span className="muted">{t(`wizard.preset.${item.key}.help`)}</span>
                  <span className="table-wizard-chips">
                    {fieldChips.map((label) => <span key={`f-${label}`} className="table-wizard-chip table-wizard-chip-linked">🔗 {label}</span>)}
                    {item.rows.filter(([label]) => label).map(([label]) => (
                      <span key={`r-${label}`} className="table-wizard-chip">{t(`wizard.presetRow.${label}`)}</span>
                    ))}
                  </span>
                </button>
              );
            })}
          </div>
        ) : null}

        <div className="table-wizard-footer">
          <button type="button" className="button-ghost" onClick={() => finish(false)}>{t("wizard.skip")}</button>
          <div className="table-wizard-footer-actions">
            <span className="muted">{t("wizard.stepOf", { step: index + 1, count: steps.length })}</span>
            {index > 0 ? <button type="button" className="button-ghost" onClick={() => setStep(index - 1)}>{t("wizard.back")}</button> : null}
            <button type="button" className="button-secondary" onClick={() => (isLast ? finish(true) : setStep(index + 1))}>
              {isLast ? t("wizard.finish") : t("wizard.next")}
            </button>
          </div>
        </div>
      </div>
      <aside className="element-create-sidebar">{preview}</aside>
    </div>
  );
}
