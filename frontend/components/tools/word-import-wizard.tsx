"use client";

import { useState } from "react";
import { Badge, BadgeVariant } from "@/components/ui/badge";
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
  WordImportTextTarget,
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

type Category = "tables" | "attendance" | "events" | "lists" | "texts";

function UploadIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" width="30" height="30">
      <path d="M12 4v11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <path d="M7.5 10.5 12 15l4.5-4.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M5 19h14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function DocIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" width="20" height="20">
      <path d="M7 3h7l4 4v14H7z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
      <path d="M14 3v4h4" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  );
}

function WarningIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" aria-hidden="true" width="18" height="18">
      <circle cx="8" cy="8" r="6.5" stroke="currentColor" strokeWidth="1.4" />
      <path d="M8 5v4" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      <circle cx="8" cy="11" r="0.75" fill="currentColor" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" aria-hidden="true" width="15" height="15">
      <path d="M3 8.5 6.2 11.5 13 4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function TableIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" width="16" height="16">
      <rect x="3.5" y="4.5" width="17" height="15" rx="2" stroke="currentColor" strokeWidth="1.5" />
      <path d="M3.5 10h17M9.5 4.5v15" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}

function PeopleIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" width="16" height="16">
      <circle cx="9" cy="8" r="3" stroke="currentColor" strokeWidth="1.5" />
      <path d="M3.5 19c0-3 2.5-5 5.5-5s5.5 2 5.5 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <circle cx="17" cy="8.5" r="2.4" stroke="currentColor" strokeWidth="1.4" />
      <path d="M15.5 14.2c2.6.2 4.6 2.1 4.6 4.8" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}

function CalendarIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" width="16" height="16">
      <rect x="3.5" y="5" width="17" height="15" rx="2" stroke="currentColor" strokeWidth="1.5" />
      <path d="M3.5 9.5h17M8 3v4M16 3v4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function ListIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" width="16" height="16">
      <circle cx="4.5" cy="6" r="1" fill="currentColor" />
      <circle cx="4.5" cy="12" r="1" fill="currentColor" />
      <circle cx="4.5" cy="18" r="1" fill="currentColor" />
      <path d="M8.5 6h12M8.5 12h12M8.5 18h12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function AlignIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" width="16" height="16">
      <path d="M4 6h16M4 12h16M4 18h10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

const CATEGORIES: { key: Category; label: string; Icon: typeof TableIcon }[] = [
  { key: "tables", label: "Tabellen", Icon: TableIcon },
  { key: "attendance", label: "Anwesenheit", Icon: PeopleIcon },
  { key: "events", label: "Termine", Icon: CalendarIcon },
  { key: "lists", label: "Listen", Icon: ListIcon },
  { key: "texts", label: "Texte", Icon: AlignIcon },
];

function roleBadgeVariant(role: TableRole): BadgeVariant {
  switch (role) {
    case "attendance":
      return "success";
    case "events":
      return "warning";
    case "list":
      return "info";
    default:
      return "neutral";
  }
}

function statusPillVariant(status: string): BadgeVariant {
  switch (status) {
    case "present":
      return "success";
    case "late":
      return "warning";
    case "excused":
      return "info";
    case "absent":
      return "danger";
    default:
      return "neutral";
  }
}

function normalizeHeaderSignature(headerCells: string[]): string {
  // Must mirror the backend's _normalize()+_fold_umlauts() exactly (same strip -> lower
  // -> fold -> collapse-whitespace order) - this key is persisted into the learned
  // WordImportProfile and looked up again via the backend's own normalization on the
  // next import. Without the umlaut fold, any header containing ä/ö/ü/ß (common in
  // German table headers like "Ämtli") would be saved under a different key than the
  // backend ever looks up, silently breaking the "don't ask again" learning for that
  // table every single time.
  const folded = headerCells
    .join(" | ")
    .trim()
    .toLowerCase()
    .replace(/ä/g, "a")
    .replace(/ö/g, "o")
    .replace(/ü/g, "u")
    .replace(/ß/g, "ss");
  return folded.replace(/\s+/g, " ");
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

// An event row only needs a decision from the user when it's linked to an EXISTING
// event whose title/date actually conflicts with the document - a row that will
// simply create a new event is a perfectly fine default, not something "open".
function eventNeedsReview(entry: EventDraft): boolean {
  const linked = entry.candidates.find((candidate) => candidate.event_id === entry.linked_event_id);
  if (!linked) return false;
  return linked.title !== entry.raw_title || linked.event_date !== (entry.raw_date ?? linked.event_date);
}

// Same idea for list rows: a brand-new entry is a fine default, but a name that
// couldn't be matched to any participant, or a column-2 value that conflicts with
// the existing entry, needs an explicit decision.
function listNeedsReview(entry: ListDraft): boolean {
  if (!entry.has_snapshot_target) return false;
  const linked = entry.candidates.find((candidate) => candidate.entry_id === entry.linked_entry_id);
  const col2Differs = !!linked && linked.column_two_display !== entry.column_two_raw;
  const hasUnmatchedName = [...entry.column_one_names, ...entry.column_two_names].some((name) => name.participant_id === null);
  return col2Differs || hasUnmatchedName;
}

function textNeedsReview(text: TextDraft): boolean {
  return text.template_element_id === null || (text.isEventRepeat && text.linkedEventId === null);
}

function attendanceNeedsReview(entry: AttendanceDraft): boolean {
  return entry.participant_id === null && !entry.createNew;
}

function textSummaryLabel(text: TextDraft, target: WordImportTextTarget | undefined, linkedEvent: WordImportEventCandidate | undefined): string {
  if (!target) return "";
  let label = target.label;
  if (text.isFormBlock) label += ` · Formular (${text.formFields.length} Feld${text.formFields.length === 1 ? "" : "er"})`;
  if (text.isEventRepeat) label += ` · pro Termin${linkedEvent ? ` → ${linkedEvent.title}` : ""}`;
  return label;
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
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);

  const [analysis, setAnalysis] = useState<WordImportAnalysis | null>(null);
  const [protocolDate, setProtocolDate] = useState("");
  const [tableRoles, setTableRoles] = useState<Record<number, TableRoleOverride>>({});
  const [texts, setTexts] = useState<TextDraft[]>([]);
  const [attendance, setAttendance] = useState<AttendanceDraft[]>([]);
  const [events, setEvents] = useState<EventDraft[]>([]);
  const [lists, setLists] = useState<ListDraft[]>([]);
  const [createdProtocolId, setCreatedProtocolId] = useState<number | null>(null);
  const [activeCategory, setActiveCategory] = useState<Category>("tables");
  const [expandedTexts, setExpandedTexts] = useState<Set<number>>(new Set());
  const [showAllAttendance, setShowAllAttendance] = useState(false);
  const [doneSummary, setDoneSummary] = useState<{ attendance: number; events: number; lists: number; skipped: number } | null>(null);

  function toggleTextExpanded(index: number) {
    setExpandedTexts((current) => {
      const next = new Set(current);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  }

  function applyAnalysis(result: WordImportAnalysis) {
    setAnalysis(result);
    setProtocolDate(result.protocol_date ?? "");
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
    setActiveCategory("tables");
    setExpandedTexts(new Set());
    setShowAllAttendance(false);
  }

  async function submitUpload() {
    if (!file || !templateId) return;
    setBusy(true);
    setError(null);
    try {
      const result = await analyzeWordImport(file, templateId, null);
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
      const result = await analyzeWordImport(file, templateId, protocolDate || null, tableRoles);
      applyAnalysis(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Datei konnte nicht erneut analysiert werden");
    } finally {
      setBusy(false);
    }
  }

  function resetWizard() {
    setStep("upload");
    setFile(null);
    setError(null);
    setAnalysis(null);
    setProtocolDate("");
    setTableRoles({});
    setTexts([]);
    setAttendance([]);
    setEvents([]);
    setLists([]);
    setCreatedProtocolId(null);
    setDoneSummary(null);
  }

  function pickFile(candidate: File | null) {
    if (candidate && !candidate.name.toLowerCase().endsWith(".docx")) return;
    setFile(candidate);
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
      const approvedAttendance = attendance.filter((entry) => entry.participant_id !== null || entry.createNew);
      const approvedEvents = events.filter((entry) => entry.approved);
      const approvedLists = lists
        .filter((entry) => entry.approved && entry.has_snapshot_target)
        .filter((entry) => (tableRoles[entry.table_index]?.list_definition_id ?? 0) > 0);
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
        attendance: approvedAttendance.map((entry) => ({
          raw_name: entry.raw_name,
          participant_id: entry.createNew ? null : entry.participant_id,
          participant_name: entry.createNew
            ? entry.raw_name
            : participants.find((participant) => participant.id === entry.participant_id)?.display_name ?? entry.raw_name,
          status: entry.status,
          create_new: entry.createNew,
        })),
        events: approvedEvents.map((entry) => {
          const resolved = resolveEventFinal(entry);
          return {
            approved: true,
            linked_event_id: entry.linked_event_id,
            final_title: resolved.title,
            final_date: resolved.date,
          };
        }),
        lists: approvedLists.map((entry) => ({
          table_index: entry.table_index,
          list_definition_id: tableRoles[entry.table_index]?.list_definition_id ?? 0,
          column_one_raw: entry.column_one_raw,
          column_two_raw: resolveListColumnTwoRaw(entry),
          column_one_names: entry.column_one_names,
          column_two_names: entry.column_two_names,
          approved: true,
          linked_entry_id: entry.linked_entry_id,
        })),
        tables: analysis.tables.map((table) => ({
          header_signature: normalizeHeaderSignature(table.header_cells),
          role: tableRoles[table.index]?.role ?? table.role,
          list_definition_id: tableRoles[table.index]?.list_definition_id ?? table.list_definition_id,
        })),
      });
      setDoneSummary({
        attendance: approvedAttendance.length,
        events: approvedEvents.length,
        lists: approvedLists.length,
        skipped:
          attendance.length -
          approvedAttendance.length +
          (events.length - approvedEvents.length) +
          (lists.filter((entry) => entry.has_snapshot_target).length - approvedLists.length) +
          texts.filter((text) => textNeedsReview(text)).length,
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
  const templateName = templates.find((template) => template.id === templateId)?.name ?? "";

  const attendanceOpen = attendance.filter(attendanceNeedsReview).length;
  const eventsOpen = events.filter(eventNeedsReview).length;
  const listsOpen = lists.filter(listNeedsReview).length;
  const textsOpen = texts.filter(textNeedsReview).length;
  const totalOpen = attendanceOpen + eventsOpen + listsOpen + textsOpen;

  const categoryCounts: Record<Category, number> = {
    tables: analysis?.tables.length ?? 0,
    attendance: attendanceOpen,
    events: eventsOpen,
    lists: listsOpen,
    texts: textsOpen,
  };
  const categoryVariants: Record<Category, BadgeVariant> = {
    tables: "neutral",
    attendance: "danger",
    events: "warning",
    lists: "warning",
    texts: "danger",
  };

  // Preserve document order: always show rows that need a decision, plus the
  // first couple of already-resolved rows for context; collapse the rest
  // behind a "N weitere automatisch zugeordnet" summary line.
  const visibleAttendance: { entry: AttendanceDraft; index: number }[] = [];
  let hiddenAttendanceCount = 0;
  {
    let okShown = 0;
    attendance.forEach((entry, index) => {
      const flagged = attendanceNeedsReview(entry);
      if (showAllAttendance || flagged || okShown < 2) {
        visibleAttendance.push({ entry, index });
        if (!flagged) okShown += 1;
      } else {
        hiddenAttendanceCount += 1;
      }
    });
  }

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
        <div className="grid word-import-narrow">
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
            <label
              className={`word-import-dropzone${isDragOver ? " is-dragover" : ""}`}
              onDragOver={(event) => {
                event.preventDefault();
                setIsDragOver(true);
              }}
              onDragLeave={() => setIsDragOver(false)}
              onDrop={(event) => {
                event.preventDefault();
                setIsDragOver(false);
                pickFile(event.dataTransfer.files?.[0] ?? null);
              }}
            >
              {file ? (
                <>
                  <span className="word-import-dropzone-icon">
                    <UploadIcon />
                  </span>
                  <strong>{file.name}</strong>
                  <span className="muted">
                    {(file.size / (1024 * 1024)).toFixed(1)} MB · zum Ersetzen klicken oder Datei hierher ziehen
                  </span>
                </>
              ) : (
                <>
                  <span className="word-import-dropzone-icon">
                    <UploadIcon />
                  </span>
                  <strong>Datei auswählen</strong>
                  <span className="muted">.docx hierher ziehen oder klicken</span>
                </>
              )}
              <input type="file" accept=".docx" onChange={(event) => pickFile(event.target.files?.[0] ?? null)} hidden />
            </label>
          </label>
          <button type="button" className="button-primary" disabled={busy || !file || !templateId} onClick={() => void submitUpload()}>
            {busy ? "…" : "Analysieren"}
          </button>
        </div>
      )}

      {step === "review" && analysis && (
        <div className="grid">
          {analysis.profile_applied && <p className="muted">Import-Vorlage aus einem früheren Import wurde angewendet.</p>}

          <div className="word-import-filebar">
            <span className="word-import-filebar-icon">
              <DocIcon />
            </span>
            <span className="word-import-filebar-meta">
              <strong>{file?.name ?? "Dokument"}</strong>
              <span className="muted"> · {templateName}</span>
              <span className="muted"> · </span>
              <input
                type="date"
                className="word-import-filebar-date"
                value={protocolDate}
                onChange={(event) => setProtocolDate(event.target.value)}
                title="Protokolldatum"
              />
            </span>
            <button type="button" className="button-ghost" disabled={busy} onClick={() => void reanalyze()}>
              {busy ? "…" : "Neu analysieren"}
            </button>
          </div>

          {!analysis.protocol_date && (
            <div className="word-import-alert">
              <WarningIcon />
              <span className="word-import-alert-date">
                Protokolldatum konnte nicht automatisch erkannt werden.
                <input
                  type="date"
                  className="input word-import-alert-date-input"
                  value={protocolDate}
                  onChange={(event) => setProtocolDate(event.target.value)}
                />
              </span>
            </div>
          )}

          {totalOpen > 0 && (
            <div className="word-import-alert">
              <WarningIcon />
              <span>
                {totalOpen} {totalOpen === 1 ? "Eintrag benötigt" : "Einträge benötigen"} eine manuelle Prüfung, bevor das Protokoll
                erstellt werden kann.
              </span>
            </div>
          )}

          <div className="word-import-layout">
            <nav className="word-import-nav">
              {CATEGORIES.map(({ key, label, Icon }) => {
                const count = categoryCounts[key];
                return (
                  <button
                    key={key}
                    type="button"
                    className={`word-import-nav-item${activeCategory === key ? " word-import-nav-item-active" : ""}`}
                    onClick={() => setActiveCategory(key)}
                  >
                    <span className="word-import-nav-item-icon">
                      <Icon />
                    </span>
                    <span className="word-import-nav-item-label">{label}</span>
                    {key === "tables" ? (
                      <Badge variant="neutral">{count}</Badge>
                    ) : count > 0 ? (
                      <Badge variant={categoryVariants[key]}>{count} offen</Badge>
                    ) : null}
                  </button>
                );
              })}
            </nav>

            <div className="word-import-panel">
              {activeCategory === "tables" && (
                <>
                  <div>
                    <h3 className="word-import-panel-title">Erkannte Tabellen</h3>
                    <p className="word-import-panel-desc">Rolle pro Tabelle zuweisen — steuert, wie Zeilen unten interpretiert werden.</p>
                  </div>
                  <div className="table-shell">
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>Tabelle</th>
                          <th>Vorschau</th>
                          <th>Rolle</th>
                          <th>Ziel</th>
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
                                  className="pill-select"
                                  data-variant={roleBadgeVariant(current.role)}
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
                                {current.role === "list" ? (
                                  <TodoAssigneeMenu
                                    label={
                                      analysis.list_definitions.find((definition) => definition.id === current.list_definition_id)
                                        ?.name ?? "– auswählen –"
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
                                ) : (
                                  <span className="muted">—</span>
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </>
              )}

              {activeCategory === "attendance" && (
                <>
                  <div>
                    <h3 className="word-import-panel-title">Anwesenheit</h3>
                    <p className="word-import-panel-desc">
                      {attendance.length} Namen im Dokument erkannt — automatisch zugeordnete Zeilen sind zusammengefasst.
                    </p>
                  </div>
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
                        {visibleAttendance.map(({ entry, index }) => {
                          const assigneeOptions: AssigneeOption[] = entry.raw_name
                            ? [{ id: CREATE_NEW_PARTICIPANT_ID, display_name: `🆕 Als neuen Teilnehmer anlegen: "${entry.raw_name}"` }, ...participants]
                            : participants;
                          const label = entry.createNew
                            ? `🆕 Neuer Teilnehmer: "${entry.raw_name}"`
                            : participants.find((participant) => participant.id === entry.participant_id)?.display_name ?? "Keinen verknüpfen";
                          return (
                            <tr key={index} className={attendanceNeedsReview(entry) ? "table-row-error" : undefined}>
                              <td>{entry.raw_name || <span className="muted">– nicht im Dokument (Standard: abwesend) –</span>}</td>
                              <td>
                                <select
                                  className="pill-select"
                                  data-variant={statusPillVariant(entry.status)}
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
                                {attendanceNeedsReview(entry) ? (
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
                                ) : (
                                  <span className="word-import-text-row-summary">
                                    <CheckIcon /> {label}
                                  </span>
                                )}
                              </td>
                            </tr>
                          );
                        })}
                        {hiddenAttendanceCount > 0 && (
                          <tr className="word-import-summary-row">
                            <td colSpan={3}>
                              <button
                                type="button"
                                className="button-inline button-ghost word-import-summary-link"
                                onClick={() => setShowAllAttendance(true)}
                              >
                                <CheckIcon /> {hiddenAttendanceCount} weitere Namen automatisch eindeutig zugeordnet
                              </button>
                            </td>
                          </tr>
                        )}
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
                </>
              )}

              {activeCategory === "events" && (
                <>
                  <div>
                    <h3 className="word-import-panel-title">Termine</h3>
                    <p className="word-import-panel-desc">Im Dokument erwähnte Anlässe mit bestehenden Terminen abgleichen.</p>
                  </div>
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
                          const hasDiff = eventNeedsReview(entry);
                          return (
                            <>
                              <tr key={entry.row_index} className={hasDiff ? "table-row-error" : undefined}>
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
                                      <span className="muted">Datum weicht ab — welchen Wert übernehmen?</span>
                                      {linked.title !== entry.raw_title && (
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
                                      {linked.event_date !== (entry.raw_date ?? linked.event_date) && (
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
                                                  current.map((row, rowIndex) =>
                                                    rowIndex === index ? { ...row, date_source: "existing" } : row
                                                  )
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
                </>
              )}

              {activeCategory === "lists" && (
                <>
                  <div>
                    <h3 className="word-import-panel-title">Listen</h3>
                    <p className="word-import-panel-desc">Erkannte Listen-Zeilen bestehenden Einträgen zuordnen.</p>
                  </div>
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
                          const needsReview = listNeedsReview(entry);
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
                              <tr key={`${entry.table_index}-${entry.row_index}`} className={needsReview ? "table-row-error" : undefined}>
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
                </>
              )}

              {activeCategory === "texts" && (
                <>
                  <div>
                    <h3 className="word-import-panel-title">Texte</h3>
                    <p className="word-import-panel-desc">Erkannte Abschnitte den Blöcken der Vorlage zuordnen.</p>
                  </div>
                  <div className="grid" style={{ gap: "10px" }}>
                    {texts.map((text, index) => {
                      const target = analysis.text_targets.find(
                        (candidate) =>
                          candidate.template_element_id === text.template_element_id && candidate.block_sort_index === text.block_sort_index
                      );
                      const linkedEvent = text.eventCandidates.find((candidate) => candidate.event_id === text.linkedEventId);
                      const flagged = textNeedsReview(text);
                      const isOpen = flagged || expandedTexts.has(index);
                      const summaryLabel = textSummaryLabel(text, target, linkedEvent);
                      return (
                        <div className={`word-import-text-row${flagged ? " word-import-flag" : ""}`} key={index}>
                          <div
                            className="word-import-text-row-head"
                            style={{ cursor: flagged ? "default" : "pointer" }}
                            onClick={() => !flagged && toggleTextExpanded(index)}
                          >
                            <span className="word-import-text-row-title">{text.extracted_heading}</span>
                            {!isOpen &&
                              (summaryLabel ? (
                                <span className="word-import-text-row-summary">
                                  <CheckIcon /> {summaryLabel}
                                </span>
                              ) : (
                                <span className="word-import-text-row-summary is-unassigned">– nicht zugewiesen –</span>
                              ))}
                          </div>
                          {isOpen && (
                            <div className="grid" style={{ gap: "10px" }}>
                              <select
                                value={targetKey(text.template_element_id, text.block_sort_index)}
                                onChange={(event) => {
                                  const [elementIdRaw, blockSortRaw] = event.target.value.split(":");
                                  const templateElementId = elementIdRaw ? Number(elementIdRaw) : null;
                                  const blockSortIndex = blockSortRaw ? Number(blockSortRaw) : null;
                                  const nextTarget = analysis.text_targets.find(
                                    (candidate) => candidate.template_element_id === templateElementId && candidate.block_sort_index === blockSortIndex
                                  );
                                  setTexts((current) =>
                                    current.map((row, rowIndex) =>
                                      rowIndex === index
                                        ? {
                                            ...row,
                                            template_element_id: templateElementId,
                                            block_sort_index: blockSortIndex,
                                            isEventRepeat: nextTarget?.is_event_repeat ?? false,
                                            linkedEventId: nextTarget?.is_event_repeat ? row.linkedEventId : null,
                                            // Switching to a different target's own row structure - use
                                            // the values already parsed for this target during analyze()
                                            // (see WordImportTextMapping.form_fields_by_target, computed
                                            // for every form target up front, not just the auto-matched
                                            // one) instead of starting blank, since a manual switch is
                                            // exactly the case where the auto-match missed.
                                            isFormBlock: nextTarget?.is_form_block ?? false,
                                            formFields: nextTarget?.is_form_block
                                              ? row.formFieldsByTarget[targetKey(templateElementId, blockSortIndex)] ??
                                                nextTarget.form_rows.map((formRow) => ({
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
                                {analysis.text_targets.map((candidate) => (
                                  <option
                                    key={targetKey(candidate.template_element_id, candidate.block_sort_index)}
                                    value={targetKey(candidate.template_element_id, candidate.block_sort_index)}
                                  >
                                    {candidate.label}
                                    {candidate.is_event_repeat ? " · pro Termin" : ""}
                                    {candidate.is_form_block ? " · Formular" : ""}
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
                          )}
                        </div>
                      );
                    })}
                    {texts.length === 0 && <p className="muted">Keine zuordenbaren Textabschnitte erkannt.</p>}
                  </div>
                </>
              )}
            </div>
          </div>

          <div className="word-import-footer">
            {totalOpen > 0 ? (
              <span className="word-import-footer-warning">{totalOpen} Einträge noch offen — sie werden beim Übernehmen ignoriert.</span>
            ) : (
              <span />
            )}
            <div className="wizard-footer-actions">
              <button type="button" className="button-ghost" onClick={() => setStep("upload")}>
                Abbrechen
              </button>
              <button type="button" className="button-primary" disabled={busy || !protocolDate} onClick={() => void submitCommit()}>
                {busy ? "…" : "Protokoll erstellen"}
              </button>
            </div>
          </div>
        </div>
      )}

      {step === "done" && createdProtocolId !== null && (
        <>
          <div className="wizard-success">
            <div className="wizard-success-icon">
              <CheckIcon />
            </div>
            <div>
              <h3 style={{ margin: "0 0 6px" }}>Protokoll erstellt</h3>
              <p className="muted word-import-success-stats">
                {doneSummary &&
                  `${doneSummary.attendance} Anwesenheiten, ${doneSummary.events} Termine und ${doneSummary.lists} Listeneinträge wurden übernommen.`}
                {doneSummary && doneSummary.skipped > 0 && (
                  <> {doneSummary.skipped} Einträge wurden übersprungen und können manuell nachgetragen werden.</>
                )}
              </p>
            </div>
          </div>
          <div className="wizard-footer">
            <button type="button" className="button-ghost" onClick={resetWizard}>
              Neuer Import
            </button>
            <div className="wizard-footer-actions">
              <a className="button-primary" href={`/protocols/${createdProtocolId}`}>
                Protokoll ansehen
              </a>
            </div>
          </div>
        </>
      )}
    </article>
  );
}
