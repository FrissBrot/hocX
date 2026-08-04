"use client";

import { useState } from "react";
import { ATTENDANCE_OPTIONS } from "@/components/protocol/protocol-editor-shared";
import { AssigneeOption, TodoAssigneeMenu } from "@/components/todos/todo-assignee-menu";
import {
  analyzeWordImport,
  commitWordImport,
  EventMatchStatus,
  ListRowStatus,
  TableRole,
  TableRoleOverride,
  WordImportAnalysis,
  WordImportEventCandidate,
  WordImportFormFieldValue,
  WordImportListEntryCandidate,
  WordImportNameResolution,
} from "@/lib/api/word-import";
import { ParticipantSummary, TemplateSummary } from "@/types/api";

type Step = "upload" | "review" | "done";

const STEPS: { key: Step; label: string }[] = [
  { key: "upload", label: "Datei wählen" },
  { key: "review", label: "Prüfen & bestätigen" },
  { key: "done", label: "Fertig" },
];

const TABLE_ROLE_OPTIONS: { value: TableRole; label: string }[] = [
  { value: "ignore", label: "Ignorieren" },
  { value: "attendance", label: "Anwesenheit" },
  { value: "events", label: "Termine" },
  { value: "list", label: "Liste" },
];

function normalizeHeaderSignature(headerCells: string[]): string {
  return headerCells.join(" | ").trim().toLowerCase().replace(/\s+/g, " ");
}

function targetKey(templateElementId: number | null, blockSortIndex: number | null): string {
  if (templateElementId === null || blockSortIndex === null) return "";
  return `${templateElementId}:${blockSortIndex}`;
}

type TextDraft = {
  extracted_heading: string;
  content: string;
  template_element_id: number | null;
  block_sort_index: number | null;
  isEventRepeat: boolean;
  eventCandidates: WordImportEventCandidate[];
  linkedEventId: number | null;
  isFormBlock: boolean;
  formFields: WordImportFormFieldValue[];
  formFieldsByTarget: Record<string, WordImportFormFieldValue[]>;
};
type AttendanceDraft = { raw_name: string; status: string; participant_id: number | null; createNew: boolean };
// Sentinel id for the "create as new participant" option in the attendance assignee menu -
// distinct from `null` (which means "don't link this row to anyone").
const CREATE_NEW_PARTICIPANT_ID = -1;
type FieldSource = "doc" | "existing";
type EventDraft = {
  row_index: number;
  raw_title: string;
  raw_date: string | null;
  status: EventMatchStatus;
  candidates: WordImportEventCandidate[];
  linked_event_id: number | null;
  title_source: FieldSource;
  date_source: FieldSource;
  approved: boolean;
};
type ListDraft = {
  table_index: number;
  row_index: number;
  column_one_raw: string;
  column_two_raw: string;
  column_one_type: string;
  column_two_type: string;
  column_one_names: WordImportNameResolution[];
  column_two_names: WordImportNameResolution[];
  status: ListRowStatus;
  candidates: WordImportListEntryCandidate[];
  linked_entry_id: number | null;
  column_two_source: FieldSource;
  has_snapshot_target: boolean;
  approved: boolean;
};

const NAME_COLUMN_TYPES = new Set(["participant", "participants"]);

function resolveEventFinal(entry: EventDraft): { title: string; date: string } {
  const linked = entry.candidates.find((candidate) => candidate.event_id === entry.linked_event_id);
  return {
    title: entry.title_source === "existing" && linked ? linked.title : entry.raw_title,
    date: entry.date_source === "existing" && linked ? linked.event_date : entry.raw_date ?? linked?.event_date ?? "",
  };
}

function resolveListColumnTwoRaw(entry: ListDraft): string {
  const linked = entry.candidates.find((candidate) => candidate.entry_id === entry.linked_entry_id);
  return entry.column_two_source === "existing" && linked ? linked.column_two_display : entry.column_two_raw;
}

export function WordImportWizard({
  templates,
  participants,
}: {
  templates: TemplateSummary[];
  participants: ParticipantSummary[];
}) {
  const [step, setStep] = useState<Step>("upload");
  const [templateId, setTemplateId] = useState<number | null>(templates[0]?.id ?? null);
  const [file, setFile] = useState<File | null>(null);
  const [dateHint, setDateHint] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [analysis, setAnalysis] = useState<WordImportAnalysis | null>(null);
  const [protocolDate, setProtocolDate] = useState("");
  const [tableRoles, setTableRoles] = useState<Record<number, TableRoleOverride>>({});
  const [texts, setTexts] = useState<TextDraft[]>([]);
  const [attendance, setAttendance] = useState<AttendanceDraft[]>([]);
  const [events, setEvents] = useState<EventDraft[]>([]);
  const [lists, setLists] = useState<ListDraft[]>([]);
  const [createdProtocolId, setCreatedProtocolId] = useState<number | null>(null);

  function applyAnalysis(result: WordImportAnalysis) {
    setAnalysis(result);
    setProtocolDate(result.protocol_date ?? dateHint ?? "");
    setTableRoles(
      Object.fromEntries(
        result.tables.map((table) => [table.index, { role: table.role, list_definition_id: table.list_definition_id }])
      )
    );
    setTexts(
      result.text_mappings.map((mapping) => ({
        extracted_heading: mapping.extracted_heading,
        content: mapping.extracted_text,
        template_element_id: mapping.template_element_id,
        block_sort_index: mapping.block_sort_index,
        isEventRepeat: mapping.is_event_repeat,
        eventCandidates: mapping.event_candidates,
        linkedEventId: mapping.matched_event_id,
        isFormBlock: mapping.is_form_block,
        formFields: mapping.form_fields,
        formFieldsByTarget: mapping.form_fields_by_target,
      }))
    );
    setAttendance(
      result.attendance_mappings.map((mapping) => ({
        raw_name: mapping.raw_name,
        status: mapping.status,
        participant_id: mapping.suggested_participant_id,
        createNew: false,
      }))
    );
    setEvents(
      result.event_mappings.map((mapping) => ({
        row_index: mapping.row_index,
        raw_title: mapping.raw_title,
        raw_date: mapping.raw_date,
        status: mapping.status,
        candidates: mapping.candidates,
        linked_event_id: mapping.status !== "new" ? mapping.matched_event_id : null,
        title_source: "doc",
        date_source: "doc",
        approved: mapping.status === "matched",
      }))
    );
    setLists(
      result.list_mappings.map((mapping) => ({
        table_index: mapping.table_index,
        row_index: mapping.row_index,
        column_one_raw: mapping.column_one_raw,
        column_two_raw: mapping.column_two_raw,
        column_one_type: mapping.column_one_type,
        column_two_type: mapping.column_two_type,
        column_one_names: mapping.column_one_names,
        column_two_names: mapping.column_two_names,
        status: mapping.status,
        candidates: mapping.candidates,
        linked_entry_id: mapping.status !== "new" ? mapping.matched_entry_id : null,
        column_two_source: "doc",
        has_snapshot_target: mapping.has_snapshot_target,
        approved: mapping.status === "matched" && mapping.has_snapshot_target,
      }))
    );
  }

  async function submitUpload() {
    if (!file || !templateId) return;
    setBusy(true);
    setError(null);
    try {
      const result = await analyzeWordImport(file, templateId, dateHint || null);
      applyAnalysis(result);
      setStep("review");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Datei konnte nicht analysiert werden");
    } finally {
      setBusy(false);
    }
  }

  async function reanalyze() {
    if (!file || !templateId) return;
    setBusy(true);
    setError(null);
    try {
      const result = await analyzeWordImport(file, templateId, protocolDate || dateHint || null, tableRoles);
      applyAnalysis(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Datei konnte nicht erneut analysiert werden");
    } finally {
      setBusy(false);
    }
  }

  function updateFormFieldValue(textIndex: number, fieldIndex: number, rawValue: string) {
    setTexts((current) =>
      current.map((row, rowIndex) =>
        rowIndex === textIndex
          ? { ...row, formFields: row.formFields.map((field, i) => (i === fieldIndex ? { ...field, raw_value: rawValue } : field)) }
          : row
      )
    );
  }

  // optionId here follows the same convention as the attendance table's assignee menu:
  // null = "keinen verknüpfen", CREATE_NEW_PARTICIPANT_ID = "als neuen Teilnehmer
  // anlegen", any other id = link to that existing Participant.
  function updateFormFieldSingleName(textIndex: number, fieldIndex: number, optionId: number | null, rawName: string) {
    setTexts((current) =>
      current.map((row, rowIndex) =>
        rowIndex === textIndex
          ? {
              ...row,
              formFields: row.formFields.map((field, i) =>
                i === fieldIndex
                  ? {
                      ...field,
                      names:
                        optionId === null
                          ? []
                          : [
                              {
                                raw_name: rawName,
                                participant_id: optionId === CREATE_NEW_PARTICIPANT_ID ? null : optionId,
                                create_new: optionId === CREATE_NEW_PARTICIPANT_ID,
                              },
                            ],
                    }
                  : field
              ),
            }
          : row
      )
    );
  }

  function updateFormFieldNameAt(textIndex: number, fieldIndex: number, nameIndex: number, optionId: number | null) {
    setTexts((current) =>
      current.map((row, rowIndex) =>
        rowIndex === textIndex
          ? {
              ...row,
              formFields: row.formFields.map((field, i) =>
                i === fieldIndex
                  ? {
                      ...field,
                      names: field.names.map((name, ni) =>
                        ni === nameIndex
                          ? {
                              ...name,
                              participant_id: optionId === CREATE_NEW_PARTICIPANT_ID ? null : optionId,
                              create_new: optionId === CREATE_NEW_PARTICIPANT_ID,
                            }
                          : name
                      ),
                    }
                  : field
              ),
            }
          : row
      )
    );
  }

  function updateListName(rowIndex: number, column: "one" | "two", nameIndex: number, participantId: number | null) {
    setLists((current) =>
      current.map((row, index) => {
        if (index !== rowIndex) return row;
        const key = column === "one" ? "column_one_names" : "column_two_names";
        const updatedNames = row[key].map((name, i) => (i === nameIndex ? { ...name, participant_id: participantId } : name));
        return { ...row, [key]: updatedNames, approved: true };
      })
    );
  }

  async function submitCommit() {
    if (!templateId || !protocolDate || !analysis) return;
    setBusy(true);
    setError(null);
    try {
      const result = await commitWordImport({
        template_id: templateId,
        protocol_date: protocolDate,
        texts: texts.map((text) => ({
          extracted_heading: text.extracted_heading,
          content: text.isFormBlock ? "" : text.content,
          template_element_id: text.template_element_id,
          block_sort_index: text.block_sort_index,
          is_event_repeat: text.isEventRepeat,
          linked_event_id: text.isEventRepeat ? text.linkedEventId : null,
          is_form_block: text.isFormBlock,
          form_fields: text.isFormBlock ? text.formFields : [],
        })),
        attendance: attendance
          .filter((entry) => entry.participant_id !== null || entry.createNew)
          .map((entry) => ({
            raw_name: entry.raw_name,
            participant_id: entry.createNew ? null : entry.participant_id,
            participant_name: entry.createNew
              ? entry.raw_name
              : participants.find((participant) => participant.id === entry.participant_id)?.display_name ?? entry.raw_name,
            status: entry.status,
            create_new: entry.createNew,
          })),
        events: events
          .filter((entry) => entry.approved)
          .map((entry) => {
            const resolved = resolveEventFinal(entry);
            return {
              approved: true,
              linked_event_id: entry.linked_event_id,
              final_title: resolved.title,
              final_date: resolved.date,
            };
          }),
        lists: lists
          .filter((entry) => entry.approved && entry.has_snapshot_target)
          .map((entry) => ({
            table_index: entry.table_index,
            list_definition_id: tableRoles[entry.table_index]?.list_definition_id ?? 0,
            column_one_raw: entry.column_one_raw,
            column_two_raw: resolveListColumnTwoRaw(entry),
            column_one_names: entry.column_one_names,
            column_two_names: entry.column_two_names,
            approved: true,
            linked_entry_id: entry.linked_entry_id,
          }))
          .filter((entry) => entry.list_definition_id > 0),
        tables: analysis.tables.map((table) => ({
          header_signature: normalizeHeaderSignature(table.header_cells),
          role: tableRoles[table.index]?.role ?? table.role,
          list_definition_id: tableRoles[table.index]?.list_definition_id ?? table.list_definition_id,
        })),
      });
      setCreatedProtocolId(result.id);
      setStep("done");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Protokoll konnte nicht erstellt werden");
    } finally {
      setBusy(false);
    }
  }

  const stepIndex = STEPS.findIndex((entry) => entry.key === step);

  return (
    <article className="card">
      <div className="wizard-steps">
        {STEPS.map((entry, index) => (
          <div className="wizard-step" key={entry.key} style={index === STEPS.length - 1 ? { flex: "0 0 auto" } : { flex: 1 }}>
            <div className={`wizard-step-dot${index === stepIndex ? " is-active" : ""}${index < stepIndex ? " is-done" : ""}`}>
              {index + 1}
            </div>
            <span className={`wizard-step-label${index === stepIndex ? " is-active" : ""}`}>{entry.label}</span>
            {index < STEPS.length - 1 && <div className={`wizard-step-line${index < stepIndex ? " is-done" : ""}`} />}
          </div>
        ))}
      </div>

      {error && <div className="form-error-banner">{error}</div>}

      {step === "upload" && (
        <div className="grid">
          <label className="field-stack">
            <span className="field-label">Vorlage</span>
            <select value={templateId ?? ""} onChange={(event) => setTemplateId(Number(event.target.value))}>
              {templates.map((template) => (
                <option key={template.id} value={template.id}>
                  {template.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field-stack">
            <span className="field-label">Word-Datei (.docx)</span>
            <input type="file" accept=".docx" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
          </label>
          <label className="field-stack">
            <span className="field-label">Protokolldatum (falls im Dokument nicht erkennbar)</span>
            <input type="date" className="input" value={dateHint} onChange={(event) => setDateHint(event.target.value)} />
          </label>
          <div className="wizard-footer">
            <span />
            <div className="wizard-footer-actions">
              <button
                type="button"
                className="button-primary"
                disabled={busy || !file || !templateId}
                onClick={() => void submitUpload()}
              >
                {busy ? "…" : "Analysieren"}
              </button>
            </div>
          </div>
        </div>
      )}

      {step === "review" && analysis && (
        <div className="grid">
          {analysis.profile_applied && <p className="muted">Import-Vorlage aus einem früheren Import wurde angewendet.</p>}
          {analysis.warnings.length > 0 && (
            <div className="form-error-banner">
              {analysis.warnings.map((warning, index) => (
                <div key={index}>{warning}</div>
              ))}
            </div>
          )}

          <label className="field-stack">
            <span className="field-label">Protokolldatum</span>
            <input type="date" className="input" value={protocolDate} onChange={(event) => setProtocolDate(event.target.value)} />
          </label>

          <h3>Erkannte Tabellen</h3>
          <div className="table-shell">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Tabelle</th>
                  <th>Vorschau</th>
                  <th>Rolle</th>
                  <th>Liste</th>
                </tr>
              </thead>
              <tbody>
                {analysis.tables.map((table) => {
                  const current = tableRoles[table.index] ?? { role: table.role, list_definition_id: table.list_definition_id };
                  return (
                    <tr key={table.index}>
                      <td>#{table.index + 1}</td>
                      <td className="muted">{table.header_cells.join(" · ")}</td>
                      <td>
                        <select
                          value={current.role}
                          onChange={(event) =>
                            setTableRoles((prev) => ({
                              ...prev,
                              [table.index]: { ...current, role: event.target.value as TableRole },
                            }))
                          }
                        >
                          {TABLE_ROLE_OPTIONS.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>
                        {current.role === "list" && (
                          <TodoAssigneeMenu
                            label={
                              analysis.list_definitions.find((definition) => definition.id === current.list_definition_id)?.name ??
                              "– auswählen –"
                            }
                            nullLabel="– auswählen –"
                            activeId={current.list_definition_id}
                            participants={analysis.list_definitions.map(
                              (definition): AssigneeOption => ({ id: definition.id, display_name: definition.name })
                            )}
                            onChange={(option) =>
                              setTableRoles((prev) => ({
                                ...prev,
                                [table.index]: { ...current, list_definition_id: option.id },
                              }))
                            }
                          />
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="wizard-footer">
            <span />
            <div className="wizard-footer-actions">
              <button type="button" className="button-ghost" disabled={busy} onClick={() => void reanalyze()}>
                {busy ? "…" : "Neu analysieren"}
              </button>
            </div>
          </div>

          <h3>Anwesenheit</h3>
          <div className="table-shell">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Im Dokument</th>
                  <th>Status</th>
                  <th>Teilnehmer</th>
                </tr>
              </thead>
              <tbody>
                {attendance.map((entry, index) => {
                  const assigneeOptions: AssigneeOption[] = entry.raw_name
                    ? [{ id: CREATE_NEW_PARTICIPANT_ID, display_name: `🆕 Als neuen Teilnehmer anlegen: "${entry.raw_name}"` }, ...participants]
                    : participants;
                  const label = entry.createNew
                    ? `🆕 Neuer Teilnehmer: "${entry.raw_name}"`
                    : participants.find((participant) => participant.id === entry.participant_id)?.display_name ?? "Keinen verknüpfen";
                  return (
                    <tr key={index} className={entry.participant_id === null && !entry.createNew ? "table-row-error" : undefined}>
                      <td>{entry.raw_name || <span className="muted">– nicht im Dokument (Standard: abwesend) –</span>}</td>
                      <td>
                        <select
                          value={entry.status}
                          onChange={(event) =>
                            setAttendance((current) =>
                              current.map((row, rowIndex) => (rowIndex === index ? { ...row, status: event.target.value } : row))
                            )
                          }
                        >
                          {ATTENDANCE_OPTIONS.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>
                        <TodoAssigneeMenu
                          label={label}
                          nullLabel="Keinen verknüpfen"
                          activeId={entry.createNew ? CREATE_NEW_PARTICIPANT_ID : entry.participant_id}
                          participants={assigneeOptions}
                          onChange={(option) =>
                            setAttendance((current) =>
                              current.map((row, rowIndex) =>
                                rowIndex === index
                                  ? option.id === CREATE_NEW_PARTICIPANT_ID
                                    ? { ...row, participant_id: null, createNew: true }
                                    : { ...row, participant_id: option.id, createNew: false }
                                  : row
                              )
                            )
                          }
                        />
                      </td>
                    </tr>
                  );
                })}
                {attendance.length === 0 && (
                  <tr>
                    <td colSpan={3} className="muted">
                      Keine Anwesenheitstabelle erkannt bzw. zugeordnet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <h3>Termine</h3>
          <div className="table-shell">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Im Dokument</th>
                  <th>Verknüpfung</th>
                  <th>Übernehmen</th>
                </tr>
              </thead>
              <tbody>
                {events.map((entry, index) => {
                  const linked = entry.candidates.find((candidate) => candidate.event_id === entry.linked_event_id);
                  const titleDiffers = !!linked && linked.title !== entry.raw_title;
                  const dateDiffers = !!linked && linked.event_date !== (entry.raw_date ?? linked.event_date);
                  const hasDiff = titleDiffers || dateDiffers;
                  return (
                    <>
                      <tr key={entry.row_index} className={entry.linked_event_id === null || hasDiff ? "table-row-error" : undefined}>
                        <td>
                          {entry.raw_title} ({entry.raw_date ?? "?"})
                        </td>
                        <td>
                          <TodoAssigneeMenu
                            label={linked ? `${linked.title} (${linked.event_date})` : "🆕 Neu anlegen"}
                            nullLabel="🆕 Neu anlegen"
                            activeId={entry.linked_event_id}
                            participants={entry.candidates.map(
                              (candidate): AssigneeOption => ({
                                id: candidate.event_id,
                                display_name: `${candidate.title} (${candidate.event_date})`,
                              })
                            )}
                            onChange={(option) =>
                              setEvents((current) =>
                                current.map((row, rowIndex) =>
                                  rowIndex === index
                                    ? { ...row, linked_event_id: option.id, title_source: "doc", date_source: "doc" }
                                    : row
                                )
                              )
                            }
                          />
                        </td>
                        <td>
                          <input
                            type="checkbox"
                            checked={entry.approved}
                            onChange={(event) =>
                              setEvents((current) =>
                                current.map((row, rowIndex) => (rowIndex === index ? { ...row, approved: event.target.checked } : row))
                              )
                            }
                          />
                        </td>
                      </tr>
                      {linked && hasDiff && (
                        <tr key={`${entry.row_index}-diff`} className="table-row-error">
                          <td colSpan={3}>
                            <div className="grid" style={{ gap: "0.35rem" }}>
                              {titleDiffers && (
                                <div className="field-stack">
                                  <span className="muted">Titel</span>
                                  <label>
                                    <input
                                      type="radio"
                                      checked={entry.title_source === "doc"}
                                      onChange={() =>
                                        setEvents((current) =>
                                          current.map((row, rowIndex) => (rowIndex === index ? { ...row, title_source: "doc" } : row))
                                        )
                                      }
                                    />{" "}
                                    aus Dokument: {entry.raw_title}
                                  </label>
                                  <label>
                                    <input
                                      type="radio"
                                      checked={entry.title_source === "existing"}
                                      onChange={() =>
                                        setEvents((current) =>
                                          current.map((row, rowIndex) => (rowIndex === index ? { ...row, title_source: "existing" } : row))
                                        )
                                      }
                                    />{" "}
                                    bestehender Wert: {linked.title}
                                  </label>
                                </div>
                              )}
                              {dateDiffers && (
                                <div className="field-stack">
                                  <span className="muted">Datum</span>
                                  <label>
                                    <input
                                      type="radio"
                                      checked={entry.date_source === "doc"}
                                      onChange={() =>
                                        setEvents((current) =>
                                          current.map((row, rowIndex) => (rowIndex === index ? { ...row, date_source: "doc" } : row))
                                        )
                                      }
                                    />{" "}
                                    aus Dokument: {entry.raw_date ?? "?"}
                                  </label>
                                  <label>
                                    <input
                                      type="radio"
                                      checked={entry.date_source === "existing"}
                                      onChange={() =>
                                        setEvents((current) =>
                                          current.map((row, rowIndex) => (rowIndex === index ? { ...row, date_source: "existing" } : row))
                                        )
                                      }
                                    />{" "}
                                    bestehender Wert: {linked.event_date}
                                  </label>
                                </div>
                              )}
                            </div>
                          </td>
                        </tr>
                      )}
                    </>
                  );
                })}
                {events.length === 0 && (
                  <tr>
                    <td colSpan={3} className="muted">
                      Keine Termin-Tabelle erkannt bzw. zugeordnet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <h3>Listen</h3>
          <div className="table-shell">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Tabelle</th>
                  <th>Spalte 1</th>
                  <th>Verknüpfung</th>
                  <th>Spalte 2</th>
                  <th>Übernehmen</th>
                </tr>
              </thead>
              <tbody>
                {lists.map((entry, index) => {
                  const linked = entry.candidates.find((candidate) => candidate.entry_id === entry.linked_entry_id);
                  const col2Differs = !!linked && linked.column_two_display !== entry.column_two_raw;
                  const col2IsText = entry.column_two_type === "text";
                  const hasUnmatchedName = [...entry.column_one_names, ...entry.column_two_names].some(
                    (name) => name.participant_id === null
                  );
                  if (!entry.has_snapshot_target) {
                    return (
                      <tr key={`${entry.table_index}-${entry.row_index}`} className="table-row-error">
                        <td>#{entry.table_index + 1}</td>
                        <td colSpan={3} className="muted">
                          {entry.column_one_raw} → {entry.column_two_raw} — Vorlage hat keinen Block für diese Liste, wird nicht
                          importiert.
                        </td>
                        <td>
                          <span className="muted">übersprungen</span>
                        </td>
                      </tr>
                    );
                  }
                  return (
                    <>
                      <tr
                        key={`${entry.table_index}-${entry.row_index}`}
                        className={entry.linked_entry_id === null || col2Differs || hasUnmatchedName ? "table-row-error" : undefined}
                      >
                        <td>#{entry.table_index + 1}</td>
                        <td>
                          {NAME_COLUMN_TYPES.has(entry.column_one_type) ? (
                            <div className="grid" style={{ gap: "0.35rem" }}>
                              {entry.column_one_names.map((name, nameIndex) => (
                                <div key={nameIndex} className="field-stack">
                                  <span className="muted">{name.raw_name}</span>
                                  <TodoAssigneeMenu
                                    label={participants.find((participant) => participant.id === name.participant_id)?.display_name ?? "Keinen verknüpfen"}
                                    nullLabel="Keinen verknüpfen"
                                    activeId={name.participant_id}
                                    participants={participants}
                                    onChange={(option) => updateListName(index, "one", nameIndex, option.id)}
                                  />
                                </div>
                              ))}
                            </div>
                          ) : (
                            entry.column_one_raw
                          )}
                        </td>
                        <td>
                          <TodoAssigneeMenu
                            label={linked ? `${linked.column_one_display} → ${linked.column_two_display}` : "🆕 Neu (nur in diesem Protokoll)"}
                            nullLabel="🆕 Neu (nur in diesem Protokoll)"
                            activeId={entry.linked_entry_id}
                            participants={entry.candidates.map(
                              (candidate): AssigneeOption => ({
                                id: candidate.entry_id,
                                display_name: `${candidate.column_one_display} → ${candidate.column_two_display}`,
                              })
                            )}
                            onChange={(option) =>
                              setLists((current) =>
                                current.map((row, rowIndex) =>
                                  rowIndex === index ? { ...row, linked_entry_id: option.id, column_two_source: "doc" } : row
                                )
                              )
                            }
                          />
                        </td>
                        <td>
                          {NAME_COLUMN_TYPES.has(entry.column_two_type) ? (
                            <div className="grid" style={{ gap: "0.35rem" }}>
                              {entry.column_two_names.map((name, nameIndex) => (
                                <div key={nameIndex} className="field-stack">
                                  <span className="muted">{name.raw_name}</span>
                                  <TodoAssigneeMenu
                                    label={participants.find((participant) => participant.id === name.participant_id)?.display_name ?? "Keinen verknüpfen"}
                                    nullLabel="Keinen verknüpfen"
                                    activeId={name.participant_id}
                                    participants={participants}
                                    onChange={(option) => updateListName(index, "two", nameIndex, option.id)}
                                  />
                                </div>
                              ))}
                              {linked && col2Differs && <div className="muted">bisher: {linked.column_two_display}</div>}
                            </div>
                          ) : (
                            <>
                              {entry.column_two_raw}
                              {linked && col2Differs && !col2IsText && <div className="muted">bisher: {linked.column_two_display}</div>}
                            </>
                          )}
                        </td>
                        <td>
                          <input
                            type="checkbox"
                            checked={entry.approved}
                            onChange={(event) =>
                              setLists((current) =>
                                current.map((row, rowIndex) => (rowIndex === index ? { ...row, approved: event.target.checked } : row))
                              )
                            }
                          />
                        </td>
                      </tr>
                      {linked && col2Differs && col2IsText && (
                        <tr key={`${entry.table_index}-${entry.row_index}-diff`} className="table-row-error">
                          <td colSpan={5}>
                            <div className="field-stack">
                              <span className="muted">Spalte 2</span>
                              <label>
                                <input
                                  type="radio"
                                  checked={entry.column_two_source === "doc"}
                                  onChange={() =>
                                    setLists((current) =>
                                      current.map((row, rowIndex) => (rowIndex === index ? { ...row, column_two_source: "doc" } : row))
                                    )
                                  }
                                />{" "}
                                aus Dokument: {entry.column_two_raw}
                              </label>
                              <label>
                                <input
                                  type="radio"
                                  checked={entry.column_two_source === "existing"}
                                  onChange={() =>
                                    setLists((current) =>
                                      current.map((row, rowIndex) =>
                                        rowIndex === index ? { ...row, column_two_source: "existing" } : row
                                      )
                                    )
                                  }
                                />{" "}
                                bestehender Wert: {linked.column_two_display}
                              </label>
                            </div>
                          </td>
                        </tr>
                      )}
                    </>
                  );
                })}
                {lists.length === 0 && (
                  <tr>
                    <td colSpan={5} className="muted">
                      Keine Listen-Tabelle erkannt bzw. zugeordnet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <h3>Texte</h3>
          {texts.map((text, index) => {
            const linkedEvent = text.eventCandidates.find((candidate) => candidate.event_id === text.linkedEventId);
            const hasError = text.template_element_id === null || (text.isEventRepeat && text.linkedEventId === null);
            return (
              <div className={`field-stack${hasError ? " table-row-error" : ""}`} key={index}>
                <span className="field-label">{text.extracted_heading}</span>
                <select
                  value={targetKey(text.template_element_id, text.block_sort_index)}
                  onChange={(event) => {
                    const [elementIdRaw, blockSortRaw] = event.target.value.split(":");
                    const templateElementId = elementIdRaw ? Number(elementIdRaw) : null;
                    const blockSortIndex = blockSortRaw ? Number(blockSortRaw) : null;
                    const target = analysis.text_targets.find(
                      (candidate) => candidate.template_element_id === templateElementId && candidate.block_sort_index === blockSortIndex
                    );
                    setTexts((current) =>
                      current.map((row, rowIndex) =>
                        rowIndex === index
                          ? {
                              ...row,
                              template_element_id: templateElementId,
                              block_sort_index: blockSortIndex,
                              isEventRepeat: target?.is_event_repeat ?? false,
                              linkedEventId: target?.is_event_repeat ? row.linkedEventId : null,
                              // Switching to a different target's own row structure - use
                              // the values already parsed for this target during analyze()
                              // (see WordImportTextMapping.form_fields_by_target, computed
                              // for every form target up front, not just the auto-matched
                              // one) instead of starting blank, since a manual switch is
                              // exactly the case where the auto-match missed.
                              isFormBlock: target?.is_form_block ?? false,
                              formFields: target?.is_form_block
                                ? row.formFieldsByTarget[targetKey(templateElementId, blockSortIndex)] ??
                                  target.form_rows.map((formRow) => ({
                                    row_id: formRow.row_id,
                                    label: formRow.label,
                                    row_type: formRow.row_type,
                                    raw_value: "",
                                    names: [],
                                  }))
                                : [],
                            }
                          : row
                      )
                    );
                  }}
                >
                  <option value="">– nicht zugewiesen –</option>
                  {analysis.text_targets.map((target) => (
                    <option key={targetKey(target.template_element_id, target.block_sort_index)} value={targetKey(target.template_element_id, target.block_sort_index)}>
                      {target.label}
                      {target.is_event_repeat ? " · pro Termin" : ""}
                      {target.is_form_block ? " · Formular" : ""}
                    </option>
                  ))}
                </select>
                {text.isEventRepeat && (
                  <label className="field-stack" style={{ gap: "0.25rem" }}>
                    <span className="muted">Aufgrund welchem Termin wird dieser Block erstellt?</span>
                    <TodoAssigneeMenu
                      label={linkedEvent ? `${linkedEvent.title} (${linkedEvent.event_date})` : "– Anlass wählen –"}
                      nullLabel="– nicht verknüpfen (Text wird nicht übernommen) –"
                      activeId={text.linkedEventId}
                      participants={text.eventCandidates.map(
                        (candidate): AssigneeOption => ({
                          id: candidate.event_id,
                          display_name: `${candidate.title} (${candidate.event_date})`,
                        })
                      )}
                      onChange={(option) =>
                        setTexts((current) =>
                          current.map((row, rowIndex) => (rowIndex === index ? { ...row, linkedEventId: option.id } : row))
                        )
                      }
                    />
                  </label>
                )}
                {text.isFormBlock ? (
                  <div className="grid" style={{ gap: "0.5rem" }}>
                    {text.formFields.map((field, fieldIndex) => (
                      <div key={field.row_id} className="field-stack" style={{ gap: "0.25rem" }}>
                        <span className="muted">{field.label}</span>
                        {field.row_type === "text" ? (
                          <textarea
                            rows={2}
                            value={field.raw_value}
                            onChange={(event) => updateFormFieldValue(index, fieldIndex, event.target.value)}
                          />
                        ) : field.row_type === "participant" ? (
                          <TodoAssigneeMenu
                            label={
                              field.names[0]?.create_new
                                ? `🆕 Neuer Teilnehmer: "${field.names[0].raw_name}"`
                                : participants.find((participant) => participant.id === field.names[0]?.participant_id)?.display_name ??
                                  field.raw_value ??
                                  "Keinen verknüpfen"
                            }
                            nullLabel="Keinen verknüpfen"
                            activeId={field.names[0]?.create_new ? CREATE_NEW_PARTICIPANT_ID : field.names[0]?.participant_id ?? null}
                            participants={
                              field.raw_value
                                ? [{ id: CREATE_NEW_PARTICIPANT_ID, display_name: `🆕 Als neuen Teilnehmer anlegen: "${field.raw_value}"` }, ...participants]
                                : participants
                            }
                            onChange={(option) => updateFormFieldSingleName(index, fieldIndex, option.id, field.raw_value)}
                          />
                        ) : field.row_type === "participants" ? (
                          field.names.length > 0 ? (
                            <div className="grid" style={{ gap: "0.35rem" }}>
                              {field.names.map((name, nameIndex) => (
                                <div key={nameIndex} className="field-stack" style={{ gap: "0.15rem" }}>
                                  <span className="muted">{name.raw_name}</span>
                                  <TodoAssigneeMenu
                                    label={
                                      name.create_new
                                        ? `🆕 Neuer Teilnehmer: "${name.raw_name}"`
                                        : participants.find((participant) => participant.id === name.participant_id)?.display_name ?? "Keinen verknüpfen"
                                    }
                                    nullLabel="Keinen verknüpfen"
                                    activeId={name.create_new ? CREATE_NEW_PARTICIPANT_ID : name.participant_id}
                                    participants={[
                                      { id: CREATE_NEW_PARTICIPANT_ID, display_name: `🆕 Als neuen Teilnehmer anlegen: "${name.raw_name}"` },
                                      ...participants,
                                    ]}
                                    onChange={(option) => updateFormFieldNameAt(index, fieldIndex, nameIndex, option.id)}
                                  />
                                </div>
                              ))}
                            </div>
                          ) : (
                            <span className="muted">{field.raw_value || "– keine Namen erkannt –"}</span>
                          )
                        ) : (
                          <span className="muted">Feldtyp &quot;{field.row_type}&quot; wird beim Import nicht unterstützt.</span>
                        )}
                      </div>
                    ))}
                    {text.formFields.length === 0 && <span className="muted">Keine Felder in diesem Formular-Block.</span>}
                  </div>
                ) : (
                  <textarea
                    rows={4}
                    value={text.content}
                    onChange={(event) =>
                      setTexts((current) =>
                        current.map((row, rowIndex) => (rowIndex === index ? { ...row, content: event.target.value } : row))
                      )
                    }
                  />
                )}
              </div>
            );
          })}

          <div className="wizard-footer">
            <button type="button" className="button-ghost" onClick={() => setStep("upload")}>
              Zurück
            </button>
            <div className="wizard-footer-actions">
              <button type="button" className="button-primary" disabled={busy || !protocolDate} onClick={() => void submitCommit()}>
                {busy ? "…" : "Protokoll erstellen"}
              </button>
            </div>
          </div>
        </div>
      )}

      {step === "done" && createdProtocolId !== null && (
        <div className="grid">
          <p>Protokoll wurde erstellt.</p>
          <a className="button-primary" href={`/protocols/${createdProtocolId}`} style={{ width: "fit-content" }}>
            Protokoll öffnen
          </a>
        </div>
      )}
    </article>
  );
}
