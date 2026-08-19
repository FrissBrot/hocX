"use client";

import { useEffect, useRef, useState } from "react";
import { Badge, BadgeVariant } from "@/components/ui/badge";
import { PillMenu } from "@/components/ui/pill-menu";
import { ATTENDANCE_OPTIONS } from "@/components/protocol/protocol-editor-shared";
import { AssigneeOption, TodoAssigneeMenu } from "@/components/todos/todo-assignee-menu";
import { browserApiFetch } from "@/lib/api/client";
import { useConfirm } from "@/contexts/confirm-context";
import { formatDate, formatDateRange } from "@/lib/utils/format";
import { EVENT_SYNC_FIELD_LABELS } from "@/lib/constants/event-sync-fields";
import {
  analyzeWordImport,
  commitWordImport,
  commitWordImportDocument,
  EventMatchStatus,
  getWordImportDocument,
  ListGroupingStrategy,
  ListRowStatus,
  reanalyzeWordImportDocument,
  saveWordImportDocumentDraft,
  TableRole,
  TableRoleOverride,
  WordImportAnalysis,
  WordImportAttendanceCandidate,
  WordImportEventCandidate,
  WordImportFormFieldValue,
  WordImportListEntryCandidate,
  WordImportMatrixColumnCandidate,
  WordImportNameResolution,
  WordImportReviewDraftJson,
  WordImportTextTarget,
} from "@/lib/api/word-import";
import { ParticipantSummary, TemplateSummary } from "@/types/api";

type Step = "upload" | "structure" | "review" | "done";

const STEPS: { key: Step; label: string }[] = [
  { key: "upload", label: "Datei wählen" },
  { key: "structure", label: "Namen & Tabellen zuweisen" },
  { key: "review", label: "Prüfen & bestätigen" },
  { key: "done", label: "Fertig" },
];

const TABLE_ROLE_OPTIONS: { value: TableRole; label: string }[] = [
  { value: "ignore", label: "Ignorieren" },
  { value: "attendance", label: "Anwesenheit" },
  { value: "events", label: "Termine" },
  { value: "list", label: "Liste" },
  { value: "matrix", label: "Matrix" },
];

const TABLE_ROLE_PILL_OPTIONS = TABLE_ROLE_OPTIONS.map((option) => ({
  ...option,
  variant: roleBadgeVariant(option.value),
}));

// Lists tab: how an ambiguous document table should be resolved into target-list rows
// when the automatic scoring (see analyze()'s grouping_strategy) picked wrong, or
// can't score at all yet (needs_manual_grouping, empty target list). Labels describe
// the raw document columns (1/2 = as they appear in the Word table), not the target
// list's own column order, since that's what's visible to the user reviewing it.
//
// grouping_strategy is data-dependent ("explode:<delimiter>"/"explode_swap:<delimiter>" -
// the server only ever offers a delimiter that actually occurs in that table's cells,
// see TablePreview.available_grouping_strategies), so the option list itself is built
// per-table from that array rather than a fixed constant.
const LIST_GROUPING_DELIMITER_LABELS: Record<string, string> = {
  comma: "Komma-getrennt",
  semicolon: "Semikolon-getrennt",
  slash: "Slash-getrennt",
  newline: "zeilengetrennt",
  space: "leerzeichengetrennt",
};

function listGroupingStrategyLabel(strategy: ListGroupingStrategy): string {
  if (strategy === "flat") return "1:1 wie im Dokument";
  if (strategy === "swap") return "1:1, Spalten vertauscht";
  if (strategy === "fill_down") return "Leere Zellen von oben übernehmen (Spalte 1)";
  const [prefix, delimiter] = strategy.split(":");
  const delimiterLabel = LIST_GROUPING_DELIMITER_LABELS[delimiter] ?? delimiter;
  if (prefix === "explode") return `Spalte 1 mehrfach (${delimiterLabel}), Spalte 2 ist die Gruppe`;
  if (prefix === "explode_swap") return `Spalte 2 mehrfach (${delimiterLabel}), Spalte 1 ist die Gruppe`;
  return strategy;
}

const ATTENDANCE_PILL_OPTIONS = ATTENDANCE_OPTIONS.map((option) => ({
  ...option,
  variant: statusPillVariant(option.value),
}));

type Category = "tables" | "names" | "attendance" | "events" | "lists" | "matrices" | "texts";

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

function WarningIcon({ title }: { title?: string } = {}) {
  return (
    <svg viewBox="0 0 16 16" fill="none" aria-hidden={title ? undefined : true} role={title ? "img" : undefined} width="18" height="18">
      {title && <title>{title}</title>}
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

function LinkIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" aria-hidden="true" width="16" height="16">
      <path
        d="M6.8 9.2 9.2 6.8M6.3 4.6l.9-.9a2.4 2.4 0 0 1 3.4 3.4l-.9.9M9.7 11.4l-.9.9a2.4 2.4 0 0 1-3.4-3.4l.9-.9"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" aria-hidden="true" width="15" height="15">
      <path d="M8 3v10M3 8h10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

function SpinnerIcon({ size = 14 }: { size?: number }) {
  return (
    <svg
      className="word-import-spinner"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      width={size}
      height={size}
    >
      <circle cx="12" cy="12" r="9.5" stroke="currentColor" strokeOpacity="0.2" strokeWidth="3" />
      <path d="M21.5 12a9.5 9.5 0 0 0-9.5-9.5" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

// Native <input type="date"> always renders its OWN text in the browser/OS locale
// (e.g. "10/14/2025" on an en-US Chrome) - CSS can't override that. To always show
// dd.mm.yyyy we overlay a formatted label on top of a fully transparent native input;
// the input still handles the click and the calendar picker, it's just invisible.
function InlineDateField({
  value,
  onChange,
  className,
  placeholder = "– Datum wählen –",
}: {
  value: string;
  onChange: (value: string) => void;
  className?: string;
  placeholder?: string;
}) {
  return (
    <span className="word-import-inline-date">
      <span className={className}>{value ? formatDate(value) : placeholder}</span>
      <input
        type="date"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-label="Datum"
      />
    </span>
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

function MatrixIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" width="16" height="16">
      <rect x="3.5" y="3.5" width="7" height="7" rx="1" stroke="currentColor" strokeWidth="1.5" />
      <rect x="13.5" y="3.5" width="7" height="7" rx="1" stroke="currentColor" strokeWidth="1.5" />
      <rect x="3.5" y="13.5" width="7" height="7" rx="1" stroke="currentColor" strokeWidth="1.5" />
      <rect x="13.5" y="13.5" width="7" height="7" rx="1" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}

function NamesIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" width="16" height="16">
      <circle cx="9" cy="9" r="3.2" stroke="currentColor" strokeWidth="1.5" />
      <path d="M4 19c0-3 2.2-5 5-5s5 2 5 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <circle cx="17.5" cy="16.5" r="2.8" stroke="currentColor" strokeWidth="1.3" />
      <path d="M19.5 18.6 21.5 20.6" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  );
}

const CATEGORIES: { key: Category; label: string; Icon: typeof TableIcon }[] = [
  { key: "tables", label: "Tabellen", Icon: TableIcon },
  { key: "names", label: "Namen klären", Icon: NamesIcon },
  { key: "attendance", label: "Anwesenheit", Icon: PeopleIcon },
  { key: "events", label: "Termine", Icon: CalendarIcon },
  { key: "lists", label: "Listen", Icon: ListIcon },
  { key: "matrices", label: "Matrizen", Icon: MatrixIcon },
  { key: "texts", label: "Texte", Icon: AlignIcon },
];

// Categories shown in the wizard's own top-level "Namen & Tabellen zuweisen" step (see
// Step/STEPS): table roles + recurring names, both of which change how the "Prüfen &
// bestätigen" step even reads a row - e.g. a resolved name can flip a list/matrix row's
// own approval, so anything that reaches full confidence as a consequence shows up in
// the review step pre-approved instead of demanding a redundant manual confirm.
const STRUCTURE_CATEGORIES: Category[] = ["tables", "names"];
const DATA_CATEGORIES: Category[] = ["attendance", "events", "lists", "matrices", "texts"];

function roleBadgeVariant(role: TableRole): BadgeVariant {
  switch (role) {
    case "attendance":
      return "success";
    case "events":
      return "warning";
    case "list":
      return "info";
    case "matrix":
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
  // Records that the user explicitly chose "nicht verknüpfen" - without it, that choice
  // is indistinguishable from "not yet decided" (both leave linkedEventId null), so the
  // row would stay flagged as needing review forever. Mirrors AttendanceDraft.linkedNone.
  linkedEventNone: boolean;
  // Explicit "Ignorieren" for a text section that couldn't be matched to any template
  // block at all (template_element_id stays null) - without it there was no way to
  // confirm "yes, this one really has nowhere to go" and the row stayed flagged forever.
  // See ListDraft.dismissed for the same idea elsewhere in this wizard.
  dismissed: boolean;
  isFormBlock: boolean;
  formFields: WordImportFormFieldValue[];
  formFieldsByTarget: Record<string, WordImportFormFieldValue[]>;
  // See WordImportTextMapping.sync_target_field/sync_field_status - only set alongside
  // isEventRepeat. syncFieldSource is the reviewer's pick for a "conflict" status
  // ("doc" keeps the extracted text, "existing" keeps the Event's current value),
  // defaulting to "existing" like the analogous title/date conflict picker below.
  syncTargetField: string | null;
  syncFieldStatus: "empty" | "match" | "conflict" | null;
  syncFieldExistingValue: string | null;
  syncFieldSource: FieldSource;
};
// `linkedNone` records that the user explicitly chose "Keinen verknüpfen" - without it,
// that choice is indistinguishable from "not yet decided" (both leave participant_id null),
// so the row would stay flagged as needing review forever.
type AttendanceDraft = {
  raw_name: string;
  status: string;
  participant_id: number | null;
  createNew: boolean;
  linkedNone: boolean;
  // What analyze() originally suggested for this row - set once when a fresh analysis
  // is applied, never touched by edit handlers afterward. Lets the backend learn from
  // rows where the human picked someone other than the top auto-suggestion.
  originallySuggestedParticipantId: number | null;
  originallySuggestedScore: number | null;
  // Ranked near-miss alternatives from analyze(), carried along purely for the
  // recurring-name clarifier (see RecurringNameGroup) - never sent back to the server.
  candidates: WordImportAttendanceCandidate[];
};
// Sentinel id for the "create as new participant" option in the attendance assignee menu -
// distinct from `null` (which means "don't link this row to anyone").
const CREATE_NEW_PARTICIPANT_ID = -1;
type FieldSource = "doc" | "existing";
type EventDraft = {
  row_index: number;
  raw_title: string;
  raw_date: string | null;
  // See WordImportEventMapping.raw_end_date - set for a document row naming a
  // "dd.mm.yyyy - dd.mm.yyyy" range, null for an ordinary single-day row. Resolved the
  // same way as the date itself (see date_source/resolveEventFinal), never edited
  // independently of it.
  raw_end_date: string | null;
  status: EventMatchStatus;
  candidates: WordImportEventCandidate[];
  linked_event_id: number | null;
  title_source: FieldSource;
  date_source: FieldSource;
  approved: boolean;
  // See ListDraft.dismissed for the same idea elsewhere in this wizard - distinguishes
  // an explicit "Ignorieren" from a still-open row that just hasn't been looked at.
  dismissed: boolean;
  // Only set for rows extracted from a Matrix "events" row - see WordImportEventMapping.
  tag: string | null;
  participant_count: number | null;
  matrix_key: string | null;
  matrix_title: string | null;
  row_id: string | null;
  row_label: string | null;
  column_key: string | null;
  column_label: string | null;
  // See AttendanceDraft.originallySuggestedParticipantId - same purpose, for the
  // top-ranked event candidate this row started with.
  originallySuggestedEventId: number | null;
  originallySuggestedScore: number | null;
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
  // Explicit "Ignorieren" decision on a row that couldn't be auto-resolved (see
  // listStillOpen) - distinct from a row that's simply unapproved-by-default (new entry,
  // nothing missing). Drives the third "Unvollständig" pill state below.
  dismissed: boolean;
  // True when column_one_raw/column_two_raw's grouping value was inferred (fill-down/
  // exploded repeat) rather than literally present in this document row - see
  // WordImportListRowMapping.group_filled. Flags this row for a closer look.
  group_filled: boolean;
  // See AttendanceDraft.originallySuggestedParticipantId - same purpose, for the
  // matched_entry_id this row started with.
  originallySuggestedEntryId: number | null;
  originallySuggestedScore: number | null;
};

type MatrixDraft = {
  table_index: number;
  matrix_key: string;
  matrix_title: string;
  row_id: string;
  row_label: string;
  row_type: string;
  column_label_raw: string;
  column_key: string | null;
  column_candidates: WordImportMatrixColumnCandidate[];
  raw_value: string;
  names: WordImportNameResolution[];
  approved: boolean;
  // See ListDraft.dismissed - same purpose.
  dismissed: boolean;
  // See AttendanceDraft.originallySuggestedParticipantId - same purpose, for the
  // matched column_key this cell started with.
  originallySuggestedColumnKey: string | null;
  originallySuggestedScore: number | null;
};

const NAME_COLUMN_TYPES = new Set(["participant", "participants"]);

// Everything a reviewer can edit in the review step, on top of what applyAnalysis derives
// fresh from an (re)analysis - saved to the queue document (see saveWordImportDocumentDraft)
// so leaving the page or reloading mid-review doesn't lose it. Table roles/protocol_date
// auto-detection are excluded on purpose: those already round-trip through the server via
// reanalyzeWordImportDocument and are baked into `analysis` itself.
type WordImportReviewDraft = {
  protocolDate: string;
  texts: TextDraft[];
  attendance: AttendanceDraft[];
  events: EventDraft[];
  lists: ListDraft[];
  matrices: MatrixDraft[];
  // Which of the wizard's own steps the reviewer was on - so reloading mid-review (e.g.
  // an accidental refresh) lands back on "Prüfen & bestätigen" instead of making them
  // click through "Namen & Tabellen zuweisen" again. Only "structure"/"review" are ever
  // written here (see the autosave effect); anything else falls back to "structure" below.
  step: Step;
};

// Best-effort parse of the opaque JSON blob loaded from the server - only shape-checked
// (right keys, right array-ness), not deeply validated, since it's the same wizard's own
// previously-saved output. Returns null for "no draft yet" (fresh document) as well as for
// anything that doesn't look like a draft at all, so callers can fall back to the freshly
// derived state without special-casing.
function parseReviewDraft(raw: WordImportReviewDraftJson | null | undefined): WordImportReviewDraft | null {
  if (!raw || typeof raw !== "object") return null;
  const { protocolDate, texts, attendance, events, lists, matrices, step } = raw as Record<string, unknown>;
  if (
    typeof protocolDate !== "string" ||
    !Array.isArray(texts) ||
    !Array.isArray(attendance) ||
    !Array.isArray(events) ||
    !Array.isArray(lists) ||
    !Array.isArray(matrices)
  ) {
    return null;
  }
  return {
    protocolDate,
    texts: texts as TextDraft[],
    attendance: attendance as AttendanceDraft[],
    events: events as EventDraft[],
    lists: lists as ListDraft[],
    matrices: matrices as MatrixDraft[],
    step: step === "review" ? "review" : "structure",
  };
}

function resolveEventFinal(entry: EventDraft): { title: string; date: string; endDate: string | null } {
  const linked = entry.candidates.find((candidate) => candidate.event_id === entry.linked_event_id);
  return {
    title: entry.title_source === "existing" && linked ? linked.title : entry.raw_title,
    date: entry.date_source === "existing" && linked ? linked.event_date : entry.raw_date ?? linked?.event_date ?? "",
    endDate: entry.date_source === "existing" && linked ? linked.event_end_date : entry.raw_end_date ?? linked?.event_end_date ?? null,
  };
}

function resolveListColumnTwoRaw(entry: ListDraft): string {
  const linked = entry.candidates.find((candidate) => candidate.entry_id === entry.linked_entry_id);
  return entry.column_two_source === "existing" && linked ? linked.column_two_display : entry.column_two_raw;
}

// A found link is the decision: once a Termin IS matched, any title/date conflict
// with the document falls back to "existing wins" (title_source/date_source) without
// blocking - the reviewer can still open the row and repoint it before committing, but
// nothing forces a confirmation click. Only a BRAND NEW event (no match at all) means
// something new is about to be created, which always needs an explicit decision -
// including the case where it has no usable date yet: WordImportEventCommit.final_date
// is required backend-side (see resolveEventFinal's "" fallback), so approving a
// dateless row would send an empty date and 422 the whole commit (see missingDate in
// renderEventRow, which additionally caps such a row at "Ignorieren"). Split from
// eventNeedsReview so it can be recomputed after an edit (typing a date, or linking an
// existing event) without going through the `approved`/`dismissed` short-circuit below
// - mirrors listStillOpen/listNeedsReview.
function eventStillOpen(entry: EventDraft): boolean {
  return entry.linked_event_id === null;
}

// Once the reviewer has explicitly taken the row (approved via the Übernehmen/
// Ignorieren pill) or dismissed it, that IS the decision - the conflict defaults to
// "existing wins" (see title_source/date_source) and the row should stop being flagged.
function eventNeedsReview(entry: EventDraft): boolean {
  if (entry.approved || entry.dismissed) return false;
  return eventStillOpen(entry);
}

// Mirrors eventStillOpen: a found link is the decision, so a matched entry auto-takes
// even if its column-2 value conflicts with the document (falls back to "existing
// wins" via column_two_source, still reachable/editable by opening the row). A
// brand-new entry (no match at all) always needs an explicit decision before it's
// committed, same as a name that couldn't be matched to any participant - neither
// case had an automatic assignment made for it. Split out from listNeedsReview so
// the "is this row actually resolved" fact can be recomputed after an edit (see
// updateListName) without going through the `approved` short-circuit below.
function listStillOpen(entry: ListDraft): boolean {
  if (!entry.has_snapshot_target) return false;
  const hasUnmatchedName = [...entry.column_one_names, ...entry.column_two_names].some(
    (name) => name.participant_id === null && !name.no_link
  );
  return entry.linked_entry_id === null || hasUnmatchedName;
}

// Mirrors eventNeedsReview: once the reviewer has explicitly taken a stance via the
// Übernehmen/Ignorieren pill, that IS the decision and the row leaves the sidebar's
// open count for good, independent of whatever raw diff remains underneath it. A row
// that's blocked (listStillOpen) but not yet explicitly dismissed keeps counting as
// open - see decisionState below, it shows as "Unvollständig" rather than "Ignorieren"
// so a default that just hasn't been looked at yet doesn't read as an active decision.
function listNeedsReview(entry: ListDraft): boolean {
  if (entry.approved || entry.dismissed) return false;
  return listStillOpen(entry);
}

// A matrix cell needs a decision when its target column couldn't be confidently
// resolved (no column_key yet - the doc header didn't clearly match a template
// column, a real participant, an event, or a list entry), or when a participant/
// participants-typed cell's name(s) couldn't be matched, mirroring listStillOpen.
function matrixStillOpen(entry: MatrixDraft): boolean {
  if (entry.column_key === null) return true;
  if (NAME_COLUMN_TYPES.has(entry.row_type)) {
    return entry.names.some((name) => name.participant_id === null && !name.no_link);
  }
  return false;
}

// Same approved/dismissed short-circuit as listNeedsReview.
function matrixNeedsReview(entry: MatrixDraft): boolean {
  if (entry.approved || entry.dismissed) return false;
  return matrixStillOpen(entry);
}

// Third pill state alongside "take"/"ignore": a row that's blocked because something
// required (a matched name, a template column/list block) couldn't be resolved
// automatically starts here instead of defaulting straight to "Ignorieren" - it still
// counts as open in the sidebar (see listNeedsReview/matrixNeedsReview) until the
// reviewer either fixes the missing link (auto-promotes to "take", see updateListName/
// updateMatrixName/resolveMatrixColumn) or explicitly clicks it away to "Ignorieren".
type RowDecision = "take" | "incomplete" | "ignore";

function decisionState(approved: boolean, stillOpenForReview: boolean): RowDecision {
  if (approved) return "take";
  if (stillOpenForReview) return "incomplete";
  return "ignore";
}

const DECISION_LABEL: Record<RowDecision, string> = {
  take: "Übernehmen",
  incomplete: "Unvollständig",
  ignore: "Ignorieren",
};

// Clicking the pill always moves it towards a settled state: "Übernehmen" and
// "Unvollständig" both collapse to an explicit "Ignorieren" (that's the one decision a
// reviewer can make about a row they don't want to fix right now), and "Ignorieren"
// flips back to "Übernehmen".
function nextDecisionPatch(decision: RowDecision): { approved: boolean; dismissed: boolean } {
  if (decision === "ignore") return { approved: true, dismissed: false };
  return { approved: false, dismissed: true };
}

// Groups the flat matrices/events state back into a card-per-column layout mirroring
// the real Matrix block in the protocol editor (.matrix-cards/.matrix-card - see
// focused-element-editor.tsx) instead of one row per cell - lets Timo review an import
// in the same shape he already knows from editing a protocol. Matrix "events" rows
// (e.g. "Daten") never produce MatrixDraft cells (see WordImportService.analyze - their
// dates are folded into the `events` state instead, carrying matrix/row/column context)
// so they're re-attached here as their own row bucket per column, alongside the plain
// text/participant(s) cells.
type MatrixCardCellRow = { kind: "cell"; entry: MatrixDraft; index: number };
type MatrixCardEventsRow = { kind: "events"; rowId: string; rowLabel: string; items: { entry: EventDraft; index: number }[] };
type MatrixCardRow = MatrixCardCellRow | MatrixCardEventsRow;

type MatrixCardColumn = {
  columnLabelRaw: string;
  columnKey: string | null;
  candidates: WordImportMatrixColumnCandidate[];
  rows: MatrixCardRow[];
};

type MatrixCardGroup = {
  matrixKey: string;
  matrixTitle: string;
  columns: MatrixCardColumn[];
};

function buildMatrixCardGroups(
  cellItems: { entry: MatrixDraft; index: number }[],
  eventItems: { entry: EventDraft; index: number }[]
): MatrixCardGroup[] {
  const order: string[] = [];
  const groups = new Map<string, MatrixCardGroup>();

  function ensureGroup(matrixKey: string, matrixTitle: string): MatrixCardGroup {
    let group = groups.get(matrixKey);
    if (!group) {
      group = { matrixKey, matrixTitle, columns: [] };
      groups.set(matrixKey, group);
      order.push(matrixKey);
    }
    return group;
  }

  function ensureColumn(
    group: MatrixCardGroup,
    columnLabelRaw: string,
    columnKey: string | null,
    candidates: WordImportMatrixColumnCandidate[]
  ): MatrixCardColumn {
    let column = group.columns.find((candidate) => candidate.columnLabelRaw === columnLabelRaw);
    if (!column) {
      column = { columnLabelRaw, columnKey, candidates, rows: [] };
      group.columns.push(column);
    } else if (columnKey && !column.columnKey) {
      column.columnKey = columnKey;
    }
    return column;
  }

  cellItems.forEach(({ entry, index }) => {
    const group = ensureGroup(entry.matrix_key, entry.matrix_title);
    const column = ensureColumn(group, entry.column_label_raw, entry.column_key, entry.column_candidates);
    column.rows.push({ kind: "cell", entry, index });
  });

  eventItems.forEach(({ entry, index }) => {
    if (!entry.matrix_key || !entry.column_label || !entry.row_id) return;
    const group = ensureGroup(entry.matrix_key, entry.matrix_title ?? "");
    const column = ensureColumn(group, entry.column_label, entry.column_key, []);
    let bucket = column.rows.find((row): row is MatrixCardEventsRow => row.kind === "events" && row.rowId === entry.row_id);
    if (!bucket) {
      bucket = { kind: "events", rowId: entry.row_id, rowLabel: entry.row_label ?? "Termine", items: [] };
      column.rows.push(bucket);
    }
    bucket.items.push({ entry, index });
  });

  return order.map((key) => groups.get(key)!);
}

// Real bug fixed here: unlike Anwesenheit/Liste/Matrix, an unresolved participant name
// inside a form block's field (e.g. "Wer geht") never blocked the commit at all - it
// just silently stayed on "Keinen verknüpfen", visually identical to a reviewer's own
// deliberate choice. Mirrors listStillOpen's hasUnmatchedName check.
function formFieldsStillOpen(text: TextDraft): boolean {
  if (!text.isFormBlock) return false;
  return text.formFields.some((field) => field.names.some((name) => name.participant_id === null && !name.create_new && !name.no_link));
}

function textNeedsReview(text: TextDraft): boolean {
  if (text.dismissed) return false;
  return (
    text.template_element_id === null ||
    (text.isEventRepeat && text.linkedEventId === null && !text.linkedEventNone) ||
    formFieldsStillOpen(text)
  );
}

function attendanceNeedsReview(entry: AttendanceDraft): boolean {
  return entry.participant_id === null && !entry.createNew && !entry.linkedNone;
}

// Minimum recurring threshold: a name mentioned only once gets resolved through its
// own row's normal picker just as fast as through the clarifier below, so only names
// that actually save repeated work are surfaced there.
const RECURRING_NAME_MIN_COUNT = 2;

function normalizeRawName(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/ä/g, "a")
    .replace(/ö/g, "o")
    .replace(/ü/g, "u")
    .replace(/ß/g, "ss")
    .replace(/\s+/g, " ");
}

type RecurringNameCounts = { attendance: number; text: number; list: number; matrix: number };

type RecurringNameGroup = {
  key: string;
  label: string;
  total: number;
  counts: RecurringNameCounts;
  // Best score seen for each candidate participant across every occurrence of this
  // name in the document, merged/deduped and capped to the top few - lets one click
  // resolve every occurrence at once instead of re-searching per row.
  candidates: WordImportAttendanceCandidate[];
};

// Scans every still-unresolved name across all four review categories and groups them
// by normalized raw text, so a name that recurs many times (e.g. a nickname the
// algorithm can't confidently place) surfaces once instead of needing the same manual
// pick repeated 10 times across the document - see applyRecurringNameEverywhere below
// for the matching bulk-apply half.
function buildRecurringNameGroups(
  attendance: AttendanceDraft[],
  texts: TextDraft[],
  lists: ListDraft[],
  matrices: MatrixDraft[]
): RecurringNameGroup[] {
  const groups = new Map<
    string,
    { label: string; counts: RecurringNameCounts; candidateScores: Map<number, WordImportAttendanceCandidate> }
  >();

  function touch(rawName: string, kind: keyof RecurringNameCounts, candidates: WordImportAttendanceCandidate[]) {
    const trimmed = rawName.trim();
    const key = normalizeRawName(trimmed);
    if (!key) return;
    let group = groups.get(key);
    if (!group) {
      group = { label: trimmed, counts: { attendance: 0, text: 0, list: 0, matrix: 0 }, candidateScores: new Map() };
      groups.set(key, group);
    }
    group.counts[kind] += 1;
    for (const candidate of candidates) {
      const existing = group.candidateScores.get(candidate.participant_id);
      if (!existing || candidate.score > existing.score) group.candidateScores.set(candidate.participant_id, candidate);
    }
  }

  attendance.forEach((row) => {
    if (attendanceNeedsReview(row)) touch(row.raw_name, "attendance", row.candidates);
  });
  texts.forEach((text) => {
    text.formFields.forEach((field) => {
      field.names.forEach((name) => {
        if (name.participant_id === null && !name.create_new && !name.no_link) touch(name.raw_name, "text", name.candidates);
      });
    });
  });
  lists.forEach((row) => {
    [...row.column_one_names, ...row.column_two_names].forEach((name) => {
      // no_link excludes an explicit "Keinen verknüpfen" decision from still counting as
      // open - without it, a name that only ever occurs in lists/matrices/plural form
      // fields (never in Anwesenheit, where "Keinen verknüpfen" already worked via
      // linkedNone) could never leave this count, permanently blocking structureReady.
      if (name.participant_id === null && !name.no_link) touch(name.raw_name, "list", name.candidates);
    });
  });
  matrices.forEach((row) => {
    row.names.forEach((name) => {
      if (name.participant_id === null && !name.no_link) touch(name.raw_name, "matrix", name.candidates);
    });
  });

  return Array.from(groups.entries())
    .map(([key, group]) => {
      const total = group.counts.attendance + group.counts.text + group.counts.list + group.counts.matrix;
      const candidates = Array.from(group.candidateScores.values())
        .sort((a, b) => b.score - a.score)
        .slice(0, 3);
      return { key, label: group.label, total, counts: group.counts, candidates };
    })
    .filter((group) => group.total >= RECURRING_NAME_MIN_COUNT)
    .sort((a, b) => b.total - a.total || a.label.localeCompare(b.label));
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
  documentId,
  onExitQueueMode,
}: {
  templates: TemplateSummary[];
  participants: ParticipantSummary[];
  // When set, the wizard resumes an already-uploaded queue document (/tools/import)
  // instead of starting from the "upload a file" step - loaded once on mount, review
  // reruns via the document-scoped reanalyze/commit endpoints (the original bytes are
  // already stored server-side, no File object needed).
  documentId?: number;
  onExitQueueMode?: () => void;
}) {
  const [step, setStep] = useState<Step>(documentId ? "structure" : "upload");
  const [templateId, setTemplateId] = useState<number | null>(templates[0]?.id ?? null);
  const [file, setFile] = useState<File | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
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
  const [matrices, setMatrices] = useState<MatrixDraft[]>([]);
  const [createdProtocolId, setCreatedProtocolId] = useState<number | null>(null);
  const [activeCategory, setActiveCategory] = useState<Category>("tables");
  const [pendingTableIndex, setPendingTableIndex] = useState<number | null>(null);
  const [expandedTexts, setExpandedTexts] = useState<Set<number>>(new Set());
  const [expandedEvents, setExpandedEvents] = useState<Set<number>>(new Set());
  const [expandedAttendance, setExpandedAttendance] = useState<Set<number>>(new Set());
  const [expandedLists, setExpandedLists] = useState<Set<number>>(new Set());
  const [doneSummary, setDoneSummary] = useState<
    { attendance: number; events: number; lists: number; matrices: number; skipped: number; warnings: string[] } | null
  >(null);
  // Participants eligible for THIS template's attendance tracking (excludes people marked
  // "keine Anwesenheitskontrolle" for the template, mirroring the backend's own attendance
  // matching pool) - falls back to the full tenant participant list until loaded so the
  // picker isn't empty while the request is in flight.
  const [attendanceParticipants, setAttendanceParticipants] = useState<ParticipantSummary[]>(participants);

  // Draft autosave (queue mode only, see saveWordImportDocumentDraft): isHydratingRef
  // suppresses the save that would otherwise fire from applyAnalysis's own state update
  // (loading a document / reanalyzing isn't a reviewer edit); pendingDraftRef always holds
  // the latest not-yet-sent draft so the unmount effect below can flush it immediately
  // instead of losing it when a pending debounce gets cancelled by navigating away.
  const isHydratingRef = useRef(false);
  const pendingDraftRef = useRef<WordImportReviewDraft | null>(null);
  const draftTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const documentIdRef = useRef(documentId);
  documentIdRef.current = documentId;
  const confirm = useConfirm();
  // Real bug fixed here: "Neu analysieren" (and changing a single table's role, which
  // reanalyzes the same way) used to silently discard every manual review decision with
  // no warning at all, in both standalone and queue mode. progressHydratingRef mirrors
  // isHydratingRef but is consumed by its own effect below (kept separate so the two
  // never race over which one resets it first) - applyAnalysis sets both together and
  // clears hasReviewProgressRef, the one below then flips hasReviewProgressRef back to
  // true the next time the reviewer actually touches Anwesenheit/Termine/Listen/
  // Matrizen/Texte state, which is what reanalyzeWithRoles below checks before wiping.
  const progressHydratingRef = useRef(false);
  const hasReviewProgressRef = useRef(false);
  // See updateTableRole's docstring - closes a click-race React state can't close on its
  // own since it only reflects the last completed render.
  const reanalyzeBusyRef = useRef(false);
  // Bumped every time applyAnalysis runs (initial load AND every reanalysis) - lets a
  // debounced draft save scheduled BEFORE a reanalysis detect that a NEWER analysis
  // generation has since started and skip itself, instead of landing AFTER the
  // reanalysis's server-side review_draft_json reset and resurrecting a draft that
  // belongs to the analysis generation before it (real race fixed here).
  const draftGenerationRef = useRef(0);

  function flushDraftSave(expectedGeneration?: number) {
    const id = documentIdRef.current;
    const draft = pendingDraftRef.current;
    if (!id || !draft) return;
    if (draftTimeoutRef.current) {
      clearTimeout(draftTimeoutRef.current);
      draftTimeoutRef.current = null;
    }
    pendingDraftRef.current = null;
    if (expectedGeneration !== undefined && expectedGeneration !== draftGenerationRef.current) return;
    void saveWordImportDocumentDraft(id, draft as unknown as WordImportReviewDraftJson).catch(() => {});
  }

  useEffect(() => {
    if (!documentId) return;
    if (isHydratingRef.current) {
      isHydratingRef.current = false;
      return;
    }
    // Only "structure"/"review" are meaningful to resume into (see WordImportReviewDraft.step)
    // - "upload" can't happen once documentId is set, and "done" means already committed, at
    // which point the backend refuses to save a draft anyway (see save_draft's status guard).
    if (step !== "structure" && step !== "review") return;
    const generation = draftGenerationRef.current;
    pendingDraftRef.current = { protocolDate, texts, attendance, events, lists, matrices, step };
    draftTimeoutRef.current = setTimeout(() => flushDraftSave(generation), 800);
    return () => {
      if (draftTimeoutRef.current) clearTimeout(draftTimeoutRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentId, protocolDate, texts, attendance, events, lists, matrices, step]);

  // See hasReviewProgressRef's declaration above - runs in both standalone and queue
  // mode (unlike the draft-autosave effect above, which is queue-only), consuming its
  // own hydration flag so the two effects never race over who resets it first.
  useEffect(() => {
    if (progressHydratingRef.current) {
      progressHydratingRef.current = false;
      return;
    }
    hasReviewProgressRef.current = true;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [texts, attendance, events, lists, matrices]);

  // Flushes on unmount specifically (empty deps => cleanup runs only when the wizard goes
  // away entirely - the queue view unmounts it both on "Zurück zur Warteschlange" and on
  // navigating elsewhere), so a change made just before leaving isn't lost to the debounce.
  useEffect(() => {
    return () => flushDraftSave();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!templateId) return;
    let cancelled = false;
    browserApiFetch<ParticipantSummary[]>(`/api/templates/${templateId}/participants`)
      .then((templateParticipants) => {
        if (cancelled) return;
        setAttendanceParticipants(templateParticipants.filter((participant) => !participant.exclude_from_attendance));
      })
      .catch(() => {
        if (!cancelled) setAttendanceParticipants(participants);
      });
    return () => {
      cancelled = true;
    };
  }, [templateId, participants]);

  useEffect(() => {
    if (!documentId) return;
    setBusy(true);
    setError(null);
    getWordImportDocument(documentId)
      .then((detail) => {
        setTemplateId(detail.template_id);
        setFileName(detail.original_filename);
        const draft = parseReviewDraft(detail.review_draft);
        applyAnalysis(detail.analysis, draft);
        setStep(draft?.step ?? "structure");
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Dokument konnte nicht geladen werden"))
      .finally(() => setBusy(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentId]);

  // Real bug fixed here: every expandable row header below was a plain <div onClick>
  // with no role/tabIndex/keyboard handler - a keyboard-only or screen-reader user could
  // never expand an already-resolved (unflagged, so not force-expanded) row to double-
  // check or correct it. Shared here so all four row kinds (Termine/Anwesenheit/Listen/
  // Texte) get the same Enter/Space activation as a native clickable element.
  function rowHeadKeyDown(toggle: () => void) {
    return (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        toggle();
      }
    };
  }

  function toggleTextExpanded(index: number) {
    setExpandedTexts((current) => {
      const next = new Set(current);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  }

  function toggleEventExpanded(index: number) {
    setExpandedEvents((current) => {
      const next = new Set(current);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  }

  function toggleAttendanceExpanded(index: number) {
    setExpandedAttendance((current) => {
      const next = new Set(current);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  }

  function toggleListExpanded(index: number) {
    setExpandedLists((current) => {
      const next = new Set(current);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  }

  function updateEventAt(index: number, patch: Partial<EventDraft>) {
    setEvents((current) => current.map((row, rowIndex) => (rowIndex === index ? { ...row, ...patch } : row)));
  }

  // Like updateListName/updateMatrixName: recomputes approved/dismissed after a genuine
  // data edit (date typed in, event re-linked, doc-vs-existing source flipped). Real bug
  // fixed here - see eventStillOpen's docstring, which already claimed this recompute
  // existed ("split out so it can be recomputed after an edit") but no call site ever
  // did it: typing the missing date on a blocked new-event row left approved/dismissed
  // both false, and decisionState(false, false) reads as "Ignorieren" - the exact
  // opposite of what the reviewer just did, and the Termin was silently never created.
  // Deliberately NOT used by the Übernehmen/Ignorieren pill itself (still plain
  // updateEventAt there, see renderEventRow), which must set approved/dismissed exactly
  // as chosen, not have it recomputed out from under the click.
  function updateEventField(index: number, patch: Partial<EventDraft>) {
    setEvents((current) =>
      current.map((row, rowIndex) => {
        if (rowIndex !== index) return row;
        const updated = { ...row, ...patch };
        return { ...updated, approved: !eventStillOpen(updated), dismissed: false };
      })
    );
  }

  // One shared row for a Termin under review, used both in the flat "Termine" tab and
  // inside a Matrix card's "events" row - identical interaction everywhere: collapsed by
  // default, click the row to expand the link-picker and (if the linked event's title/date
  // actually differs from the document) the doc-vs-existing choice for each field, and an
  // Übernehmen/Ignorieren button pair at the end that both selects AND confirms the
  // decision - independent of expand state so it stays reachable while collapsed. New
  // links always default back to "existing" data, matching the global default that DB
  // data wins unless explicitly swapped to the doc's.
  function renderEventRow(entry: EventDraft, index: number) {
    const linked = entry.candidates.find((candidate) => candidate.event_id === entry.linked_event_id);
    const flagged = eventNeedsReview(entry);
    const isOpen = flagged || expandedEvents.has(index);
    const titleDiffers = !!linked && linked.title !== entry.raw_title;
    const dateDiffers =
      !!linked &&
      (linked.event_date !== (entry.raw_date ?? linked.event_date) ||
        (linked.event_end_date ?? null) !== (entry.raw_end_date ?? linked.event_end_date ?? null));
    const missingDate = !linked && !entry.raw_date;
    const decision = decisionState(entry.approved, flagged);
    const isIgnored = decision === "ignore";
    return (
      <div
        className={`word-import-text-row${flagged ? " word-import-flag" : ""}${isIgnored ? " word-import-text-row-muted" : ""}`}
        key={entry.row_index}
      >
        <div
          className="word-import-text-row-head word-import-text-row-head-clickable"
          role="button"
          tabIndex={0}
          onClick={() => toggleEventExpanded(index)}
          onKeyDown={rowHeadKeyDown(() => toggleEventExpanded(index))}
        >
          <span className="word-import-text-row-title">
            {entry.raw_title} ({entry.raw_date ? formatDateRange(entry.raw_date, entry.raw_end_date) : "kein Datum"})
            {entry.participant_count !== null && <span className="muted"> · {entry.participant_count} TN</span>}
          </span>
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            {!isOpen &&
              (linked ? (
                <span className="word-import-text-row-summary">
                  {titleDiffers || dateDiffers ? (
                    // Matched-but-differs rows deliberately don't force a confirmation click
                    // (see eventStillOpen's docstring - the reviewer can still open and
                    // repoint the row before committing) but were previously visually
                    // indistinguishable from a clean match while collapsed, so a conflict
                    // could go unnoticed in a long, mostly-skimmed list (audit E3/F3,
                    // 2026-08-16). This icon is purely a "look inside" signal, not a block.
                    <WarningIcon title="Titel/Datum weichen vom Dokument ab - Zeile öffnen zum Prüfen" />
                  ) : (
                    <CheckIcon />
                  )}{" "}
                  {linked.title} ({formatDateRange(linked.event_date, linked.event_end_date)})
                </span>
              ) : (
                <span className="word-import-text-row-summary is-new">
                  <PlusIcon /> Neu anlegen
                </span>
              ))}
            <button
              type="button"
              className={`word-import-decision-btn is-${decision}`}
              onClick={(clickEvent) => {
                clickEvent.stopPropagation();
                const patch = nextDecisionPatch(decision);
                // A brand-new event with no date can never validly be "übernommen" -
                // final_date is required backend-side (see resolveEventFinal's "" ->
                // 422 for the whole commit) and there is no per-row error to point at
                // the cause. missingDate is exactly what keeps eventStillOpen true, so
                // this row must stay capped at "Ignorieren" (reachable via the normal
                // incomplete->ignore step) until a date is typed into the field above -
                // real bug fixed here: "Unvollständig"->"Ignorieren"->"Übernehmen" used
                // to reach "Übernehmen" regardless.
                if (patch.approved && missingDate) return;
                updateEventAt(index, patch);
              }}
            >
              <CheckIcon /> {DECISION_LABEL[decision]}
            </button>
          </div>
        </div>
        {isOpen && (
          <div className="grid" style={{ gap: "10px" }}>
            {missingDate && (
              <div className="word-import-alert word-import-alert-block">
                <WarningIcon />
                <span className="word-import-alert-date">
                  Kein Datum im Dokument erkannt - ohne Datum kann kein neuer Termin angelegt werden.
                  <InlineDateField
                    className="input word-import-alert-date-input"
                    value={entry.raw_date ?? ""}
                    onChange={(value) => updateEventField(index, { raw_date: value || null })}
                  />
                </span>
              </div>
            )}
            <TodoAssigneeMenu
              label={linked ? `${linked.title} (${formatDateRange(linked.event_date, linked.event_end_date)})` : "🆕 Neu anlegen"}
              nullLabel="🆕 Neu anlegen"
              activeId={entry.linked_event_id}
              participants={entry.candidates.map(
                (candidate): AssigneeOption => ({
                  id: candidate.event_id,
                  display_name: `${candidate.title} (${formatDateRange(candidate.event_date, candidate.event_end_date)})`,
                })
              )}
              onChange={(option) =>
                updateEventField(index, { linked_event_id: option.id, title_source: "existing", date_source: "existing" })
              }
            />
            {linked && (titleDiffers || dateDiffers) && (
              <div className="word-import-alert word-import-alert-block">
                <WarningIcon />
                <div className="grid" style={{ gap: "10px" }}>
                  <span>Welchen Wert übernehmen?</span>
                  {titleDiffers && (
                    <div className="word-import-diff-options">
                      <label className="field-radio-option">
                        <input
                          type="radio"
                          checked={entry.title_source === "doc"}
                          onChange={() => updateEventField(index, { title_source: "doc" })}
                        />
                        <span>
                          <span className="field-radio-option-label">Aus Dokument</span>
                          <strong>{entry.raw_title}</strong>
                        </span>
                      </label>
                      <label className="field-radio-option">
                        <input
                          type="radio"
                          checked={entry.title_source === "existing"}
                          onChange={() => updateEventField(index, { title_source: "existing" })}
                        />
                        <span>
                          <span className="field-radio-option-label">Bestehend</span>
                          <strong>{linked.title}</strong>
                        </span>
                      </label>
                    </div>
                  )}
                  {dateDiffers && (
                    <div className="word-import-diff-options">
                      <label className="field-radio-option">
                        <input
                          type="radio"
                          checked={entry.date_source === "doc"}
                          onChange={() => updateEventField(index, { date_source: "doc" })}
                        />
                        <span>
                          <span className="field-radio-option-label">Aus Dokument</span>
                          <strong>{(entry.raw_date && formatDateRange(entry.raw_date, entry.raw_end_date)) || "?"}</strong>
                        </span>
                      </label>
                      <label className="field-radio-option">
                        <input
                          type="radio"
                          checked={entry.date_source === "existing"}
                          onChange={() => updateEventField(index, { date_source: "existing" })}
                        />
                        <span>
                          <span className="field-radio-option-label">Bestehend</span>
                          <strong>{formatDateRange(linked.event_date, linked.event_end_date)}</strong>
                        </span>
                      </label>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    );
  }

  // Same collapsed-by-default / click-to-expand card as renderEventRow, reused for every
  // attendance row - ALL rows render here (no "N weitere automatisch zugeordnet" summary
  // line anymore), since the reviewer wants to be able to see and, if needed, correct every
  // participant at a glance rather than only the ones that failed to auto-match.
  function renderAttendanceRow(entry: AttendanceDraft, index: number) {
    const flagged = attendanceNeedsReview(entry);
    const isOpen = flagged || expandedAttendance.has(index);
    // A row not linked to any participant is never actually imported (see submitCommit's
    // approvedAttendance filter) - showing a specific Anwesend/Abwesend pill on it implies a
    // real decision was made about a real person, which is misleading (this can just as
    // easily be a parsing artifact like a table's "Total" row). Gray the whole row out and
    // drop the status control until it's actually linked to someone.
    const isLinked = entry.participant_id !== null || entry.createNew;
    // A participant already linked to a different row that was actually found in the
    // document may not be picked again here - that would silently link the same person
    // twice. Rows with no raw_name are the "not found in document, defaults to absent"
    // placeholders (see applyAnalysis) and are deliberately excluded from this check:
    // reassigning one of those participants to a real document row is exactly how such a
    // placeholder gets resolved.
    const takenElsewhere = new Set(
      attendance
        .filter((row, rowIndex) => rowIndex !== index && row.raw_name)
        .map((row) => row.participant_id)
        .filter((id): id is number => id !== null)
    );
    const assigneeOptions: AssigneeOption[] = (entry.raw_name
      ? [{ id: CREATE_NEW_PARTICIPANT_ID, display_name: `🆕 Als neuen Teilnehmer anlegen: "${entry.raw_name}"` }, ...attendanceParticipants]
      : attendanceParticipants
    ).filter((option) => option.id === CREATE_NEW_PARTICIPANT_ID || !takenElsewhere.has(option.id as number));
    const label = entry.createNew
      ? `🆕 Neuer Teilnehmer: "${entry.raw_name}"`
      : attendanceParticipants.find((participant) => participant.id === entry.participant_id)?.display_name ??
        participants.find((participant) => participant.id === entry.participant_id)?.display_name ??
        "Keinen verknüpfen";
    return (
      <div
        className={`word-import-text-row${flagged ? " word-import-flag" : ""}${isLinked ? "" : " word-import-text-row-muted"}`}
        key={index}
      >
        <div
          className="word-import-text-row-head word-import-text-row-head-clickable"
          role="button"
          tabIndex={0}
          onClick={() => toggleAttendanceExpanded(index)}
          onKeyDown={rowHeadKeyDown(() => toggleAttendanceExpanded(index))}
        >
          <span className="word-import-text-row-title">
            {entry.raw_name || <span className="muted">– nicht im Dokument (Standard: abwesend) –</span>}
          </span>
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            {!isOpen &&
              (isLinked ? (
                <span className="word-import-text-row-summary">
                  <CheckIcon /> {label}
                </span>
              ) : entry.linkedNone ? (
                <span className="word-import-text-row-summary is-ignored">Keinen verknüpfen</span>
              ) : (
                <span className="word-import-text-row-summary is-unassigned">– nicht zugewiesen –</span>
              ))}
            {isLinked ? (
              <span onClick={(clickEvent) => clickEvent.stopPropagation()}>
                <PillMenu
                  value={entry.status}
                  options={ATTENDANCE_PILL_OPTIONS}
                  onChange={(status) =>
                    setAttendance((current) => current.map((row, rowIndex) => (rowIndex === index ? { ...row, status } : row)))
                  }
                />
              </span>
            ) : (
              <span className="muted">–</span>
            )}
          </div>
        </div>
        {isOpen && (
          <TodoAssigneeMenu
            label={label}
            nullLabel="Keinen verknüpfen"
            activeId={entry.createNew ? CREATE_NEW_PARTICIPANT_ID : entry.participant_id}
            participants={assigneeOptions}
            onChange={(option) =>
              setAttendance((current) => {
                const updated = current.map((row, rowIndex) =>
                  rowIndex === index
                    ? option.id === CREATE_NEW_PARTICIPANT_ID
                      ? { ...row, participant_id: null, createNew: true, linkedNone: false }
                      : { ...row, participant_id: option.id, createNew: false, linkedNone: option.id === null }
                    : row
                );
                // Linking this document row to a participant who was only present as a
                // "not found in document" placeholder (see applyAnalysis) makes that
                // placeholder row redundant - drop it, otherwise the participant would be
                // submitted twice.
                if (option.id === null || option.id === CREATE_NEW_PARTICIPANT_ID) return updated;
                return updated.filter(
                  (row, rowIndex) => rowIndex === index || !(row.raw_name === "" && row.participant_id === option.id)
                );
              })
            }
          />
        )}
      </div>
    );
  }

  // Same card shape and Übernehmen/Ignorieren decision button as renderEventRow, reused
  // for list rows so the whole importer shares one visual/interaction language.
  function renderListRow(entry: ListDraft, index: number) {
    const key = `${entry.table_index}-${entry.row_index}`;
    if (!entry.has_snapshot_target) {
      return (
        <div className="word-import-text-row word-import-text-row-muted" key={key}>
          <div className="word-import-text-row-head">
            <span className="word-import-text-row-title">
              {entry.column_one_raw} → {entry.column_two_raw}
            </span>
            <span className="word-import-text-row-summary is-ignored">übersprungen</span>
          </div>
          <p className="muted" style={{ margin: 0 }}>
            Tabelle #{entry.table_index + 1}: Vorlage hat keinen Block für diese Liste, wird nicht importiert.
          </p>
        </div>
      );
    }
    const linked = entry.candidates.find((candidate) => candidate.entry_id === entry.linked_entry_id);
    const col2Differs = !!linked && linked.column_two_display !== entry.column_two_raw;
    const col2IsText = entry.column_two_type === "text";
    const col1IsNames = NAME_COLUMN_TYPES.has(entry.column_one_type);
    const col2IsNames = NAME_COLUMN_TYPES.has(entry.column_two_type);
    const flagged = listNeedsReview(entry);
    const isOpen = flagged || expandedLists.has(index);
    const decision = decisionState(entry.approved, flagged);
    const isIgnored = decision === "ignore";
    const titleLabel = col1IsNames
      ? entry.column_one_names.map((name) => name.raw_name).join(", ") || entry.column_one_raw
      : entry.column_one_raw;
    return (
      <div
        className={`word-import-text-row${flagged ? " word-import-flag" : ""}${isIgnored ? " word-import-text-row-muted" : ""}`}
        key={key}
      >
        <div
          className="word-import-text-row-head word-import-text-row-head-clickable"
          role="button"
          tabIndex={0}
          onClick={() => toggleListExpanded(index)}
          onKeyDown={rowHeadKeyDown(() => toggleListExpanded(index))}
        >
          <span className="word-import-text-row-title">
            {titleLabel}
            {!col2IsNames && entry.column_two_raw && <span className="muted"> · {entry.column_two_raw}</span>}
            {entry.group_filled && (
              <span className="muted" title="Automatisch ergänzt (Gruppierung) – bitte prüfen" style={{ marginLeft: "6px" }}>
                ✨
              </span>
            )}
          </span>
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            {!isOpen &&
              (linked ? (
                <span className="word-import-text-row-summary">
                  {col2Differs ? (
                    // See the matching comment on the event row's summary above (audit
                    // E3/F3, 2026-08-16) - purely a "look inside" signal, not a block.
                    <WarningIcon title="Wert weicht vom Dokument ab - Zeile öffnen zum Prüfen" />
                  ) : (
                    <CheckIcon />
                  )}{" "}
                  {linked.column_one_display} → {linked.column_two_display}
                </span>
              ) : (
                <span className="word-import-text-row-summary is-new">
                  <PlusIcon /> Neu (nur in diesem Protokoll)
                </span>
              ))}
            <button
              type="button"
              className={`word-import-decision-btn is-${decision}`}
              onClick={(clickEvent) => {
                clickEvent.stopPropagation();
                const patch = nextDecisionPatch(decision);
                setLists((current) => current.map((row, rowIndex) => (rowIndex === index ? { ...row, ...patch } : row)));
              }}
            >
              <CheckIcon /> {DECISION_LABEL[decision]}
            </button>
          </div>
        </div>
        {isOpen && (
          <div className="grid" style={{ gap: "10px" }}>
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
                  current.map((row, rowIndex) => {
                    if (rowIndex !== index) return row;
                    const updatedRow = { ...row, linked_entry_id: option.id, column_two_source: "doc" as FieldSource };
                    // Mirrors updateEventField: picking a link here IS the decision, so
                    // recompute approved right away instead of leaving it false and
                    // having decisionState(false, false) misread the row as "Ignorieren".
                    return { ...updatedRow, approved: !listStillOpen(updatedRow), dismissed: false };
                  })
                )
              }
            />
            {(entry.column_one_type === "text" || entry.column_two_type === "text") && (
              <div className="grid" style={{ gap: "0.35rem", gridTemplateColumns: "1fr 1fr" }}>
                {entry.column_one_type === "text" && (
                  <div className="field-stack">
                    <span className="muted">Spalte 1</span>
                    <input
                      type="text"
                      value={entry.column_one_raw}
                      onChange={(event) => {
                        const value = event.target.value;
                        setLists((current) =>
                          current.map((row, rowIndex) => (rowIndex === index ? { ...row, column_one_raw: value } : row))
                        );
                      }}
                    />
                  </div>
                )}
                {entry.column_two_type === "text" && (
                  <div className="field-stack">
                    <span className="muted">Spalte 2</span>
                    <input
                      type="text"
                      value={entry.column_two_raw}
                      onChange={(event) => {
                        const value = event.target.value;
                        setLists((current) =>
                          current.map((row, rowIndex) => (rowIndex === index ? { ...row, column_two_raw: value } : row))
                        );
                      }}
                    />
                  </div>
                )}
              </div>
            )}
            {col1IsNames && (
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
            )}
            {col2IsNames ? (
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
              linked &&
              col2Differs &&
              col2IsText && (
                <div className="word-import-alert word-import-alert-block">
                  <WarningIcon />
                  <div className="grid" style={{ gap: "10px" }}>
                    <span>Spalte 2 weicht ab — welchen Wert übernehmen?</span>
                    <div className="word-import-diff-options">
                      <label className="field-radio-option">
                        <input
                          type="radio"
                          checked={entry.column_two_source === "doc"}
                          onChange={() =>
                            setLists((current) =>
                              current.map((row, rowIndex) => (rowIndex === index ? { ...row, column_two_source: "doc" } : row))
                            )
                          }
                        />
                        <span>
                          <span className="field-radio-option-label">Aus Dokument</span>
                          <strong>{entry.column_two_raw}</strong>
                        </span>
                      </label>
                      <label className="field-radio-option">
                        <input
                          type="radio"
                          checked={entry.column_two_source === "existing"}
                          onChange={() =>
                            setLists((current) =>
                              current.map((row, rowIndex) => (rowIndex === index ? { ...row, column_two_source: "existing" } : row))
                            )
                          }
                        />
                        <span>
                          <span className="field-radio-option-label">Bestehend</span>
                          <strong>{linked.column_two_display}</strong>
                        </span>
                      </label>
                    </div>
                  </div>
                </div>
              )
            )}
          </div>
        )}
      </div>
    );
  }

  function applyAnalysis(result: WordImportAnalysis, draft?: WordImportReviewDraft | null) {
    // See draftGenerationRef's declaration - every applyAnalysis call starts a new
    // draft generation, invalidating any still-pending save scheduled before it. Also
    // drops any already-pending draft outright (not just its timer) - the autosave
    // effect's hydration early-return below never overwrites pendingDraftRef, so
    // without this an unmount right after a reanalysis (before any other edit re-
    // populates it) would still flush the STALE pre-reanalysis draft on cleanup, which
    // calls flushDraftSave() with no generation to check against.
    draftGenerationRef.current += 1;
    pendingDraftRef.current = null;
    if (draftTimeoutRef.current) {
      clearTimeout(draftTimeoutRef.current);
      draftTimeoutRef.current = null;
    }
    // Suppresses the draft-autosave effect for the state update this triggers - loading or
    // reanalyzing a document isn't itself a reviewer edit worth saving back.
    isHydratingRef.current = true;
    // Same idea for hasReviewProgressRef (see its declaration) - this state update is a
    // fresh baseline, not itself a reviewer edit worth protecting against the NEXT
    // reanalysis. EXCEPT when a saved draft is being restored here (documentId load
    // effect below): that draft IS real, already-invested review progress the reviewer
    // would lose if they click "Neu analysieren" without ever having touched anything
    // else first - seeding this to true in that case is what makes the very next
    // reanalyze correctly ask for confirmation instead of silently wiping it.
    progressHydratingRef.current = true;
    hasReviewProgressRef.current = !!draft;
    setAnalysis(result);
    setProtocolDate(draft ? draft.protocolDate : result.protocol_date ?? "");
    setTableRoles(
      Object.fromEntries(
        result.tables.map((table) => [
          table.index,
          {
            role: table.role,
            list_definition_id: table.list_definition_id,
            matrix_key: table.matrix_key,
            // Real bug fixed here: omitting this meant a manually forced grouping
            // strategy snapped back to "Automatisch" right after being applied, and -
            // worse - updateTableRole builds its NEXT reanalyze payload from this same
            // tableRoles state, so the forced strategy silently reverted to
            // auto-scoring on the very next reanalysis triggered by any OTHER table's
            // role changing.
            list_grouping_strategy: table.grouping_strategy,
          },
        ])
      )
    );
    const freshTexts: TextDraft[] = result.text_mappings.map((mapping) => ({
      extracted_heading: mapping.extracted_heading,
      content: mapping.extracted_text,
      template_element_id: mapping.template_element_id,
      block_sort_index: mapping.block_sort_index,
      isEventRepeat: mapping.is_event_repeat,
      eventCandidates: mapping.event_candidates,
      linkedEventId: mapping.matched_event_id,
      linkedEventNone: false,
      dismissed: false,
      isFormBlock: mapping.is_form_block,
      formFields: mapping.form_fields,
      formFieldsByTarget: mapping.form_fields_by_target,
      syncTargetField: mapping.sync_target_field,
      syncFieldStatus: mapping.sync_field_status,
      syncFieldExistingValue: mapping.sync_field_existing_value,
      syncFieldSource: "existing",
    }));
    const freshAttendance: AttendanceDraft[] = result.attendance_mappings.map((mapping) => ({
      raw_name: mapping.raw_name,
      status: mapping.status,
      participant_id: mapping.suggested_participant_id,
      createNew: false,
      // See WordImportAttendanceMapping.remembered_no_link - this raw name (e.g. a
      // table's own "Total" footer row) was already explicitly resolved as "Keinen
      // verknüpfen" before, so it starts pre-resolved instead of flagged for review.
      linkedNone: mapping.remembered_no_link,
      originallySuggestedParticipantId: mapping.suggested_participant_id,
      originallySuggestedScore:
        mapping.candidates.find((c) => c.participant_id === mapping.suggested_participant_id)?.score ?? null,
      candidates: mapping.candidates,
    }));
    const freshEvents: EventDraft[] = result.event_mappings.map((mapping) => {
      const draft: EventDraft = {
        row_index: mapping.row_index,
        raw_title: mapping.raw_title,
        raw_date: mapping.raw_date,
        raw_end_date: mapping.raw_end_date,
        status: mapping.status,
        candidates: mapping.candidates,
        linked_event_id: mapping.status !== "new" ? mapping.matched_event_id : null,
        // See WordImportEventMapping.remembered_title_source/remembered_date_source -
        // this exact conflict was already resolved identically in an earlier import, so
        // it's pre-applied (and the row pre-approved below) instead of asking again.
        title_source: mapping.remembered_title_source ?? "existing",
        date_source: mapping.remembered_date_source ?? "existing",
        approved: false,
        dismissed: false,
        tag: mapping.tag,
        participant_count: mapping.participant_count,
        matrix_key: mapping.matrix_key,
        matrix_title: mapping.matrix_title,
        row_id: mapping.row_id,
        row_label: mapping.row_label,
        column_key: mapping.column_key,
        column_label: mapping.column_label,
        originallySuggestedEventId: mapping.status !== "new" ? mapping.matched_event_id : null,
        originallySuggestedScore: mapping.candidates.find((c) => c.event_id === mapping.matched_event_id)?.score ?? null,
      };
      // A matched/changed Termin auto-approves - the link itself is the decision, see
      // eventStillOpen. A brand-new Termin (no link found) stays unapproved so the
      // reviewer must explicitly confirm creating it - unless this exact resolution
      // was already made identically in an earlier import (see WordImportEventMapping.
      // remembered_title_source/remembered_date_source above), in which case it's
      // pre-applied instead of asking again.
      draft.approved =
        !eventStillOpen(draft) || mapping.remembered_title_source !== null || mapping.remembered_date_source !== null;
      return draft;
    });
    const freshLists: ListDraft[] = result.list_mappings.map((mapping) => {
      const draft: ListDraft = {
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
        column_two_source: "existing",
        has_snapshot_target: mapping.has_snapshot_target,
        approved: false,
        dismissed: false,
        group_filled: mapping.group_filled,
        originallySuggestedEntryId: mapping.status !== "new" ? mapping.matched_entry_id : null,
        originallySuggestedScore: mapping.candidates.find((c) => c.entry_id === mapping.matched_entry_id)?.score ?? null,
      };
      // Same rationale as freshEvents above - a matched/changed list row auto-approves
      // since the link is the decision, while a brand-new row (no match found) or one
      // with an unresolved participant name stays unapproved until the reviewer
      // explicitly confirms it. has_snapshot_target is kept as an explicit gate (not
      // just folded into listStillOpen) since listStillOpen itself already treats "no
      // snapshot target" as "nothing to review" (true either way it's silently skipped
      // at commit) - approved would otherwise become true for a row that can never
      // actually be written.
      draft.approved = mapping.has_snapshot_target && !listStillOpen(draft);
      return draft;
    });
    const freshMatrices: MatrixDraft[] = result.matrix_mappings.map((mapping) => ({
      table_index: mapping.table_index,
      matrix_key: mapping.matrix_key,
      matrix_title: mapping.matrix_title,
      row_id: mapping.row_id,
      row_label: mapping.row_label,
      row_type: mapping.row_type,
      column_label_raw: mapping.column_label_raw,
      column_key: mapping.column_key,
      column_candidates: mapping.column_candidates,
      raw_value: mapping.raw_value,
      names: mapping.names,
      approved:
        mapping.column_key !== null &&
        !(NAME_COLUMN_TYPES.has(mapping.row_type) && mapping.names.some((name) => name.participant_id === null)),
      dismissed: false,
      originallySuggestedColumnKey: mapping.column_key,
      originallySuggestedScore: mapping.column_candidates.find((c) => c.column_key === mapping.column_key)?.score ?? null,
    }));
    // A saved draft is always tied 1:1 to this exact analysis_snapshot_json (reanalyzing a
    // document explicitly wipes review_draft_json server-side - see
    // WordImportQueueService._reanalyze_document - specifically so a stale draft can never
    // reach here), so it's safe to apply it wholesale whenever present. This used to be
    // gated on the draft's row count still matching the freshly derived one, meant to catch
    // exactly that "reanalyzed since saved" case - but the backend already rules that out,
    // and the length check actively broke legitimate edits that change a category's row
    // count on their own (e.g. linking an attendance row to a participant who was also
    // present as an unlinked "not in document" placeholder de-dupes that placeholder away,
    // see renderAttendanceRow) - the draft would then permanently fail the length check on
    // every future reload and silently revert to the fresh, unedited suggestions.
    const eventsToUse = draft ? draft.events : freshEvents;
    setTexts(draft ? draft.texts : freshTexts);
    setAttendance(draft ? draft.attendance : freshAttendance);
    setEvents(eventsToUse);
    setLists(draft ? draft.lists : freshLists);
    setMatrices(draft ? draft.matrices : freshMatrices);
    // Real bug fixed here: always "tables" regardless of the restored draft's own
    // step - a draft resumed at step "review" landed on the Structure step's own
    // "Erkannte Tabellen" panel body (activeCategory isn't gated on step, so nothing
    // in the nav even showed as active) instead of the data category the normal
    // structure->review transition uses (see "Weiter zu den Daten" above).
    setActiveCategory(draft?.step === "review" ? "attendance" : "tables");
    setExpandedTexts(new Set());
    setExpandedEvents(new Set());
    setExpandedAttendance(new Set());
    setExpandedLists(new Set());
  }

  async function submitUpload() {
    if (!file || !templateId) return;
    setBusy(true);
    setError(null);
    try {
      const result = await analyzeWordImport(file, templateId, null);
      applyAnalysis(result);
      setStep("structure");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Datei konnte nicht analysiert werden");
    } finally {
      setBusy(false);
    }
  }

  async function reanalyzeWithRoles(nextTableRoles: Record<number, TableRoleOverride>) {
    // Real bug fixed here: reanalyzeBusyRef is set to true by the caller (updateTableRole/
    // reanalyze) BEFORE calling this - either early return below used to leave it stuck at
    // true forever (both callers guard on it and bail out immediately), permanently
    // deadlocking every future reanalyze trigger for this wizard instance. Currently latent
    // (both conditions require state the callers themselves already ensure can't happen),
    // but a real leak in an otherwise careful guard.
    if (!templateId) {
      reanalyzeBusyRef.current = false;
      setPendingTableIndex(null);
      return;
    }
    if (!documentId && !file) {
      reanalyzeBusyRef.current = false;
      setPendingTableIndex(null);
      return;
    }
    // Real bug fixed here: this used to always wipe every already-reviewed Anwesenheit/
    // Termine/Listen/Matrizen/Texte decision back to fresh auto-suggestions with zero
    // warning (see hasReviewProgressRef's declaration). Only asks when there's actually
    // something at stake - a routine table-role pick during initial setup, before any
    // real review happened, still goes through with no interruption.
    if (hasReviewProgressRef.current) {
      const proceed = await confirm({
        title: "Neu analysieren?",
        message:
          "Bereits geprüfte Einträge (Anwesenheit, Termine, Listen, Matrizen, Texte) werden dabei durch frische Vorschläge ersetzt und gehen verloren. Fortfahren?",
        confirmLabel: "Neu analysieren",
        tone: "danger",
      });
      if (!proceed) {
        reanalyzeBusyRef.current = false;
        setPendingTableIndex(null);
        return;
      }
    }
    setTableRoles(nextTableRoles);
    setBusy(true);
    setError(null);
    try {
      const result = documentId
        ? await reanalyzeWordImportDocument(documentId, protocolDate || null, nextTableRoles)
        : await analyzeWordImport(file!, templateId, protocolDate || null, nextTableRoles);
      applyAnalysis(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Datei konnte nicht erneut analysiert werden");
    } finally {
      setBusy(false);
      setPendingTableIndex(null);
      reanalyzeBusyRef.current = false;
    }
  }

  // Reassigning a table's role (e.g. "Liste"/"Matrix"/Ziel) changes how its rows must be
  // interpreted, so it has to go back through the server-side parser rather than just
  // updating local state - otherwise the attendance/events/lists/matrices tabs would keep
  // showing stale rows derived from the table's previous role.
  //
  // Real bug fixed here: `busy` (React state) is only current as of the last render, so
  // two clicks on two DIFFERENT tables' role pills within the same tick could both read
  // `busy === false` and both fire, each computed from the same stale `tableRoles`
  // snapshot - whichever reanalysis resolves last silently reverts the other one's
  // change with no error. reanalyzeBusyRef is set synchronously, closing that window.
  function updateTableRole(tableIndex: number, patch: Partial<TableRoleOverride>) {
    if (reanalyzeBusyRef.current) return;
    reanalyzeBusyRef.current = true;
    const current = tableRoles[tableIndex] ?? { role: "ignore" as TableRole, list_definition_id: null, matrix_key: null };
    setPendingTableIndex(tableIndex);
    void reanalyzeWithRoles({ ...tableRoles, [tableIndex]: { ...current, ...patch } });
  }

  async function reanalyze() {
    if (reanalyzeBusyRef.current) return;
    reanalyzeBusyRef.current = true;
    await reanalyzeWithRoles(tableRoles);
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
    setMatrices([]);
    setCreatedProtocolId(null);
    setDoneSummary(null);
  }

  function pickFile(candidate: File | null) {
    if (candidate && !/\.(docx|pdf)$/i.test(candidate.name)) return;
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
      current.map((row, rowIndex) => {
        if (rowIndex !== textIndex) return row;
        const updatedRow = {
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
                            // Only ever reached for optionId !== null - the null
                            // ("Keinen verknüpfen") case takes the names: [] branch
                            // above instead, so no_link is never true here.
                            no_link: false,
                            // A brand-new name entry typed by the reviewer here, not
                            // something analyze() suggested - nothing to compare
                            // against, so there's no original suggestion.
                            originally_suggested_participant_id: null,
                            originally_suggested_score: null,
                            candidates: field.names[0]?.candidates ?? [],
                          },
                        ],
                }
              : field
          ),
        };
        // Mirrors updateListName/updateMatrixName: resolving the last open name on this
        // row must clear a stale "Ignorieren" from before the row was fully filled in,
        // otherwise the row silently stays dismissed at commit despite looking resolved.
        return { ...updatedRow, dismissed: formFieldsStillOpen(updatedRow) ? row.dismissed : false };
      })
    );
  }

  function updateFormFieldNameAt(textIndex: number, fieldIndex: number, nameIndex: number, optionId: number | null) {
    setTexts((current) =>
      current.map((row, rowIndex) => {
        if (rowIndex !== textIndex) return row;
        const updatedRow = {
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
                          // See WordImportNameResolution.no_link - explicit "Keinen
                          // verknüpfen" here must be distinguishable from never having
                          // been reviewed, otherwise the recurring-name clarifier can
                          // never count this name as resolved.
                          no_link: optionId === null,
                        }
                      : name
                  ),
                }
              : field
          ),
        };
        // See updateFormFieldSingleName above - same reset, same reason.
        return { ...updatedRow, dismissed: formFieldsStillOpen(updatedRow) ? row.dismissed : false };
      })
    );
  }

  // Picking a name is the review action itself - it auto-confirms the row the moment
  // every remaining issue on it (all names matched, no lingering column-2 conflict) is
  // actually resolved, not just because *a* name was touched (a multi-name row with one
  // name still unmatched must stay open, see listStillOpen).
  function updateListName(rowIndex: number, column: "one" | "two", nameIndex: number, participantId: number | null) {
    setLists((current) =>
      current.map((row, index) => {
        if (index !== rowIndex) return row;
        const key = column === "one" ? "column_one_names" : "column_two_names";
        const updatedNames = row[key].map((name, i) =>
          i === nameIndex ? { ...name, participant_id: participantId, no_link: participantId === null } : name
        );
        const updatedRow = { ...row, [key]: updatedNames };
        return { ...updatedRow, approved: !listStillOpen(updatedRow), dismissed: false };
      })
    );
  }

  function updateMatrixName(rowIndex: number, nameIndex: number, participantId: number | null) {
    setMatrices((current) =>
      current.map((row, index) => {
        if (index !== rowIndex) return row;
        const updatedNames = row.names.map((name, i) =>
          i === nameIndex ? { ...name, participant_id: participantId, no_link: participantId === null } : name
        );
        const updatedRow = { ...row, names: updatedNames };
        return { ...updatedRow, approved: !matrixStillOpen(updatedRow), dismissed: false };
      })
    );
  }

  // The recurring-name clarifier's bulk-apply half (see buildRecurringNameGroups) -
  // applies one decision to every still-unresolved occurrence of `key` (normalized raw
  // name) across all four categories at once, using each category's own existing
  // single-row semantics (see updateFormFieldSingleName/updateListName/updateMatrixName
  // above) so the result is indistinguishable from resolving every row by hand:
  //   optionId === null                    -> "Keinen verknüpfen"
  //   optionId === CREATE_NEW_PARTICIPANT_ID -> "Neuen Teilnehmer anlegen"
  //   optionId === <id>                    -> link to that existing Participant
  // List/Matrix names never supported "neuen Teilnehmer anlegen" even in their own
  // per-row picker (no such option is offered there), so the createNew case simply
  // leaves those entries at participant_id=null - already their unresolved state, i.e.
  // a no-op for them, same as the plain "Keinen verknüpfen" case.
  function applyRecurringNameEverywhere(key: string, optionId: number | null) {
    const participantId = optionId === CREATE_NEW_PARTICIPANT_ID ? null : optionId;
    const createNew = optionId === CREATE_NEW_PARTICIPANT_ID;

    setAttendance((current) => {
      const updated = current.map((row) =>
        row.raw_name && normalizeRawName(row.raw_name) === key && attendanceNeedsReview(row)
          ? { ...row, participant_id: participantId, createNew, linkedNone: optionId === null }
          : row
      );
      // Same dedup as the single-row assignee picker (see renderAttendanceRow): linking a
      // document row to a participant who was only present as a "not found in document"
      // roster placeholder makes that placeholder redundant - drop it, otherwise the
      // participant would be submitted twice. Only applies for a real existing-participant
      // link, matching the single-row handler's own guard.
      if (participantId === null) return updated;
      return updated.filter((row) => !(row.raw_name === "" && row.participant_id === participantId));
    });
    setTexts((current) =>
      current.map((text) => {
        let touched = false;
        const formFields = text.formFields.map((field) => {
          if (field.row_type === "participant") {
            const name = field.names[0];
            if (!name || name.participant_id !== null || name.create_new || normalizeRawName(name.raw_name) !== key) return field;
            touched = true;
            return {
              ...field,
              names:
                optionId === null
                  ? []
                  : [
                      {
                        raw_name: name.raw_name,
                        participant_id: participantId,
                        create_new: createNew,
                        // Only reached for optionId !== null (the null case takes the
                        // names: [] branch above), so never true here - see
                        // WordImportNameResolution.no_link.
                        no_link: false,
                        originally_suggested_participant_id: null,
                        originally_suggested_score: null,
                        candidates: name.candidates,
                      },
                    ],
            };
          }
          if (field.row_type === "participants") {
            let fieldTouched = false;
            const names = field.names.map((name) => {
              if (name.participant_id !== null || name.create_new || normalizeRawName(name.raw_name) !== key) return name;
              fieldTouched = true;
              return { ...name, participant_id: participantId, create_new: createNew, no_link: optionId === null };
            });
            if (fieldTouched) touched = true;
            return { ...field, names };
          }
          return field;
        });
        // Same guard as setLists/setMatrices below - only rows this bulk action actually
        // touched may have their dismissed state recomputed, otherwise clarifying one
        // recurring name would silently un-ignore unrelated rows a reviewer already
        // dismissed on purpose.
        if (!touched) return text;
        const updatedText = { ...text, formFields };
        return { ...updatedText, dismissed: formFieldsStillOpen(updatedText) ? text.dismissed : false };
      })
    );
    setLists((current) =>
      current.map((row) => {
        const matches = (name: WordImportNameResolution) => name.participant_id === null && normalizeRawName(name.raw_name) === key;
        // Only rows that actually contain this recurring name may have their
        // approved/dismissed state recomputed below - otherwise every OTHER row's
        // explicit "Ignorieren" decision would be silently reverted to "Übernehmen" by
        // clarifying an unrelated name (real bug: listStillOpen/matrixStillOpen were
        // being recomputed for the whole table on every call, not just affected rows).
        if (!row.column_one_names.some(matches) && !row.column_two_names.some(matches)) return row;
        const updated = {
          ...row,
          column_one_names: row.column_one_names.map((name) =>
            matches(name) ? { ...name, participant_id: participantId, no_link: optionId === null } : name
          ),
          column_two_names: row.column_two_names.map((name) =>
            matches(name) ? { ...name, participant_id: participantId, no_link: optionId === null } : name
          ),
        };
        return { ...updated, approved: !listStillOpen(updated), dismissed: false };
      })
    );
    setMatrices((current) =>
      current.map((row) => {
        const matches = (name: WordImportNameResolution) => name.participant_id === null && normalizeRawName(name.raw_name) === key;
        // See the same guard in setLists above - same bug, same fix.
        if (!row.names.some(matches)) return row;
        const updatedNames = row.names.map((name) =>
          matches(name) ? { ...name, participant_id: participantId, no_link: optionId === null } : name
        );
        const updatedRow = { ...row, names: updatedNames };
        return { ...updatedRow, approved: !matrixStillOpen(updatedRow), dismissed: false };
      })
    );
  }

  // Picking a column in the card header must resolve EVERY cell sharing that same
  // (matrix, doc column) - not just one row - since the backend computes column
  // resolution once per table, shared across all its rows (see column_resolution in
  // WordImportService.analyze).
  function resolveMatrixColumn(matrixKey: string, columnLabelRaw: string, columnKey: string) {
    setMatrices((current) =>
      current.map((row) => {
        if (row.matrix_key !== matrixKey || row.column_label_raw !== columnLabelRaw) return row;
        const updatedRow = { ...row, column_key: columnKey };
        // Real bug fixed here: every cell in an unresolved column starts blocked
        // (column_key === null), so picking the column genuinely affects all of them -
        // but a reviewer may have already explicitly clicked "Ignorieren" on some cell
        // (e.g. a garbage/footer row) BEFORE resolving the column. Recomputing
        // approved/dismissed unconditionally silently reverted that explicit decision
        // back to "Übernehmen". Once a row has an explicit decision (approved OR
        // dismissed), only its column_key updates here - only still-undecided
        // ("Unvollständig") rows auto-promote.
        if (row.approved || row.dismissed) return updatedRow;
        return { ...updatedRow, approved: !matrixStillOpen(updatedRow), dismissed: false };
      })
    );
  }

  async function submitCommit() {
    if (!templateId || !protocolDate || !analysis) return;
    setBusy(true);
    setError(null);
    try {
      // linkedNone rows are included too (not just linked/createNew ones) - an explicit
      // "Keinen verknüpfen" decision must reach the backend so it can be remembered (see
      // WordImportService.commit's no_link_name_updates) instead of silently vanishing;
      // commit() itself still skips writing any attendance entry for participant_id=null.
      const approvedAttendance = attendance.filter((entry) => entry.participant_id !== null || entry.createNew || entry.linkedNone);
      const approvedEvents = events.filter((entry) => entry.approved);
      const approvedLists = lists
        .filter((entry) => entry.approved && entry.has_snapshot_target)
        .filter((entry) => (tableRoles[entry.table_index]?.list_definition_id ?? 0) > 0);
      const approvedMatrices = matrices.filter((entry) => entry.approved && entry.column_key !== null);
      const payload = {
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
          dismissed: text.dismissed,
          sync_field_source: text.syncFieldStatus === "conflict" ? text.syncFieldSource : null,
        })),
        attendance: approvedAttendance.map((entry) => ({
          raw_name: entry.raw_name,
          participant_id: entry.createNew ? null : entry.participant_id,
          participant_name: entry.createNew
            ? entry.raw_name
            : participants.find((participant) => participant.id === entry.participant_id)?.display_name ?? entry.raw_name,
          status: entry.status,
          create_new: entry.createNew,
          originally_suggested_participant_id: entry.originallySuggestedParticipantId,
          originally_suggested_score: entry.originallySuggestedScore,
        })),
        events: approvedEvents.map((entry) => {
          const resolved = resolveEventFinal(entry);
          return {
            approved: true,
            linked_event_id: entry.linked_event_id,
            final_title: resolved.title,
            final_date: resolved.date,
            final_end_date: resolved.endDate,
            raw_title: entry.raw_title,
            raw_date: entry.raw_date,
            raw_end_date: entry.raw_end_date,
            tag: entry.tag,
            participant_count: entry.participant_count,
            originally_suggested_event_id: entry.originallySuggestedEventId,
            originally_suggested_score: entry.originallySuggestedScore,
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
          originally_suggested_entry_id: entry.originallySuggestedEntryId,
          originally_suggested_score: entry.originallySuggestedScore,
        })),
        matrices: approvedMatrices.map((entry) => ({
          matrix_key: entry.matrix_key,
          row_id: entry.row_id,
          row_type: entry.row_type,
          column_key: entry.column_key as string,
          column_label:
            entry.column_candidates.find((candidate) => candidate.column_key === entry.column_key)?.label ?? entry.column_label_raw,
          raw_value: entry.raw_value,
          names: entry.names,
          approved: true,
          originally_suggested_column_key: entry.originallySuggestedColumnKey,
          originally_suggested_score: entry.originallySuggestedScore,
        })),
        tables: analysis.tables.map((table) => ({
          header_signature: normalizeHeaderSignature(table.header_cells),
          role: tableRoles[table.index]?.role ?? table.role,
          list_definition_id: tableRoles[table.index]?.list_definition_id ?? table.list_definition_id,
          matrix_key: tableRoles[table.index]?.matrix_key ?? table.matrix_key,
          list_grouping_strategy: tableRoles[table.index]?.list_grouping_strategy ?? table.grouping_strategy,
          originally_suggested_role: table.role,
          originally_suggested_score: table.role_is_explicit ? 1.0 : null,
        })),
      };
      const result = documentId ? await commitWordImportDocument(documentId, payload) : await commitWordImport(payload);
      setDoneSummary({
        attendance: approvedAttendance.length,
        events: approvedEvents.length,
        lists: approvedLists.length,
        matrices: approvedMatrices.length,
        // Minor accuracy fix: the lists/texts terms used to diverge from the exact
        // filters approvedLists/approvedAttendance etc. are built from above (lists
        // dropped the list_definition_id > 0 condition; texts counted a row the
        // reviewer explicitly dismissed - or an event-repeat explicitly left
        // unlinked via "nicht verknüpfen" - as if it were still an unresolved
        // oversight rather than a deliberate, correct decision).
        skipped:
          attendance.length -
          approvedAttendance.length +
          (events.length - approvedEvents.length) +
          (lists.filter(
            (entry) => entry.has_snapshot_target && (tableRoles[entry.table_index]?.list_definition_id ?? 0) > 0
          ).length -
            approvedLists.length) +
          (matrices.length - approvedMatrices.length) +
          texts.filter(
            (text) =>
              !text.dismissed &&
              !text.linkedEventNone &&
              (text.template_element_id === null || (text.isEventRepeat && text.linkedEventId === null))
          ).length,
        warnings: result.warnings,
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

  // Matrix "events" rows (e.g. "Daten") never produce a MatrixDraft cell (see
  // buildMatrixCardGroups) - they live in `events` alongside ordinary Termine-table
  // rows, distinguished only by matrix_key. Split once here so the Termine tab shows
  // only the latter, while the Matrizen tab's cards re-absorb the former.
  const plainEventItems = events.map((entry, index) => ({ entry, index })).filter((item) => item.entry.matrix_key === null);
  const matrixEventItems = events.map((entry, index) => ({ entry, index })).filter((item) => item.entry.matrix_key !== null);
  const matrixCellItems = matrices.map((entry, index) => ({ entry, index }));
  const matrixCardGroups = buildMatrixCardGroups(matrixCellItems, matrixEventItems);

  const attendanceOpen = attendance.filter(attendanceNeedsReview).length;
  const eventsOpen = plainEventItems.filter((item) => eventNeedsReview(item.entry)).length;
  const listsOpen = lists.filter(listNeedsReview).length;
  const matricesOpen = matrices.filter(matrixNeedsReview).length + matrixEventItems.filter((item) => eventNeedsReview(item.entry)).length;
  const textsOpen = texts.filter(textNeedsReview).length;
  const totalOpen = attendanceOpen + eventsOpen + listsOpen + matricesOpen + textsOpen;

  // Each occurrence bundled here is already counted in attendanceOpen/listsOpen/
  // matricesOpen (or, for form fields, not gated on totalOpen at all - see
  // textNeedsReview) - this is a cross-cutting VIEW over the same rows, not additional
  // work, so it's deliberately excluded from totalOpen to avoid double-counting.
  const recurringNameGroups = buildRecurringNameGroups(attendance, texts, lists, matrices);
  const namesOpen = recurringNameGroups.length;

  // A table still needs a decision when its role implies a target that wasn't picked
  // yet - mirrors the warning states already shown inline in the Tabellen tab (the
  // grouping-strategy hint, the empty "– auswählen –" pickers) rather than introducing
  // a new definition of "done". Gates the structure -> data phase transition below.
  const tablesOpen = (analysis?.tables ?? []).filter((table) => {
    const current = tableRoles[table.index] ?? { role: table.role, list_definition_id: table.list_definition_id };
    if (current.role === "list") {
      if (current.list_definition_id === null) return true;
      if (table.needs_manual_grouping && !current.list_grouping_strategy) return true;
    }
    if (current.role === "matrix" && !current.matrix_key) return true;
    return false;
  }).length;
  const structureReady = tablesOpen === 0 && namesOpen === 0;

  const categoryCounts: Record<Category, number> = {
    tables: analysis?.tables.length ?? 0,
    names: namesOpen,
    attendance: attendanceOpen,
    events: eventsOpen,
    lists: listsOpen,
    matrices: matricesOpen,
    texts: textsOpen,
  };
  const categoryVariants: Record<Category, BadgeVariant> = {
    tables: "neutral",
    names: "warning",
    attendance: "warning",
    events: "warning",
    lists: "warning",
    matrices: "warning",
    texts: "warning",
  };

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

      {(step === "structure" || step === "review") && !analysis && busy && <p className="muted">Dokument wird geladen…</p>}

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
            <span className="field-label">Word- oder PDF-Datei (.docx, .pdf)</span>
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
                  <span className="muted">.docx/.pdf hierher ziehen oder klicken</span>
                </>
              )}
              <input type="file" accept=".docx,.pdf" onChange={(event) => pickFile(event.target.files?.[0] ?? null)} hidden />
            </label>
          </label>
          <button type="button" className="button-primary" disabled={busy || !file || !templateId} onClick={() => void submitUpload()}>
            {busy ? "…" : "Analysieren"}
          </button>
        </div>
      )}

      {(step === "structure" || step === "review") && analysis && (
        <div className="grid">
          {analysis.profile_applied && <p className="muted">Import-Vorlage aus einem früheren Import wurde angewendet.</p>}

          <div className="word-import-filebar">
            <span className="word-import-filebar-icon">
              <DocIcon />
            </span>
            <span className="word-import-filebar-meta">
              <strong>{fileName ?? file?.name ?? "Dokument"}</strong>
              <span className="muted"> · {templateName}</span>
              <span className="muted"> · </span>
              <InlineDateField
                className="word-import-filebar-date"
                value={protocolDate}
                onChange={setProtocolDate}
              />
            </span>
            <button type="button" className="button-ghost" disabled={busy} onClick={() => void reanalyze()}>
              {busy ? (
                <span className="word-import-cell-with-spinner">
                  <SpinnerIcon size={12} /> Neu analysieren
                </span>
              ) : (
                "Neu analysieren"
              )}
            </button>
          </div>

          {!analysis.protocol_date && (
            <div className="word-import-alert">
              <WarningIcon />
              <span className="word-import-alert-date">
                Protokolldatum konnte nicht automatisch erkannt werden.
                <InlineDateField
                  className="input word-import-alert-date-input"
                  value={protocolDate}
                  onChange={setProtocolDate}
                />
              </span>
            </div>
          )}

          {analysis.warnings.length > 0 && (
            // Real bug fixed here: analyze() has always produced these (e.g. a Matrix-
            // Zeile that couldn't be assigned to any row and is silently skipped, or an
            // unresolved table), but the frontend never rendered them anywhere - some
            // describe data that's dropped entirely and therefore has no row of its own
            // in the wizard to flag, making the loss invisible to the reviewer.
            <details className="word-import-alert word-import-alert-block">
              <summary style={{ cursor: "pointer" }}>
                <WarningIcon /> {analysis.warnings.length} Hinweis{analysis.warnings.length === 1 ? "" : "e"} zur Analyse
              </summary>
              <ul style={{ margin: "8px 0 0", paddingLeft: "18px" }}>
                {analysis.warnings.map((warning, index) => (
                  <li key={index}>{warning}</li>
                ))}
              </ul>
            </details>
          )}

          {/* Real bug fixed here: the queue's own duplicate hint only ever compares
              against other WordImportDocument rows, so this standalone wizard (which
              never creates one, see commitWordImport) was completely blind to an
              already-existing protocol for the same template+date - the same old
              protocol could be imported twice with zero warning. Queue mode already
              has its own duplicate hint in the table view, so this only needs to show
              up here. */}
          {!documentId && analysis.duplicate_protocols.length > 0 && (
            <div className="word-import-alert">
              <WarningIcon />
              <span>
                Mögliches Duplikat: Für dieses Datum existiert bereits{" "}
                {analysis.duplicate_protocols.map((duplicate, index) => (
                  <span key={duplicate.id}>
                    {index > 0 && ", "}
                    <a className="row-text-action" href={`/protocols/${duplicate.id}`} target="_blank" rel="noreferrer">
                      „{duplicate.title || duplicate.protocol_number}“
                    </a>
                  </span>
                ))}
                . Bitte prüfen, ob dieses Dokument nicht bereits importiert wurde.
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
              {CATEGORIES.filter(({ key }) => (step === "structure" ? STRUCTURE_CATEGORIES : DATA_CATEGORIES).includes(key)).map(
                ({ key, label, Icon }) => {
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
                }
              )}
              {step === "structure" ? (
                <button
                  type="button"
                  className="word-import-nav-phase-btn"
                  disabled={!structureReady}
                  onClick={() => {
                    setStep("review");
                    setActiveCategory("attendance");
                  }}
                >
                  Weiter zu den Daten →
                  {!structureReady && (
                    <span className="word-import-nav-phase-hint">
                      erst {[tablesOpen > 0 ? `${tablesOpen} Tabelle${tablesOpen === 1 ? "" : "n"}` : null, namesOpen > 0 ? `${namesOpen} Name${namesOpen === 1 ? "" : "n"}` : null]
                        .filter(Boolean)
                        .join(" & ")}{" "}
                      klären
                    </span>
                  )}
                </button>
              ) : (
                <button
                  type="button"
                  className="word-import-nav-phase-btn is-back"
                  onClick={() => {
                    setStep("structure");
                    setActiveCategory(namesOpen > 0 ? "names" : "tables");
                  }}
                >
                  ← Zurück zu Namen &amp; Tabellen
                </button>
              )}
            </nav>

            <div className="word-import-panel">
              {activeCategory === "tables" && (
                <>
                  <div>
                    <h3 className="word-import-panel-title">Erkannte Tabellen</h3>
                    <p className={`word-import-panel-desc${busy ? " word-import-panel-desc-busy" : ""}`}>
                      {busy ? (
                        <>
                          <SpinnerIcon /> Wird neu analysiert…
                        </>
                      ) : (
                        "Rolle pro Tabelle zuweisen — steuert, wie Zeilen unten interpretiert werden."
                      )}
                    </p>
                  </div>
                  {busy && (
                    <div className="word-import-progress-track">
                      <div className="word-import-progress-bar" />
                    </div>
                  )}
                  <div className={`table-shell${busy ? " word-import-panel-busy" : ""}`}>
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>Tabelle</th>
                          <th>Vorschau</th>
                          <th>Rolle</th>
                          <th>Ziel</th>
                          <th>Gruppierung</th>
                        </tr>
                      </thead>
                      <tbody>
                        {analysis.tables.map((table) => {
                          const current = tableRoles[table.index] ?? { role: table.role, list_definition_id: table.list_definition_id };
                          const isPending = pendingTableIndex === table.index;
                          return (
                            <tr key={table.index} className={isPending ? "word-import-row-pending" : undefined}>
                              <td>#{table.index + 1}</td>
                              <td className="muted">{table.header_cells.join(" · ")}</td>
                              <td>
                                <span className="word-import-cell-with-spinner">
                                  <PillMenu
                                    value={current.role}
                                    options={TABLE_ROLE_PILL_OPTIONS}
                                    onChange={(role) => updateTableRole(table.index, { role })}
                                  />
                                  {isPending && <SpinnerIcon size={12} />}
                                </span>
                              </td>
                              <td>
                                <span className="word-import-cell-with-spinner">
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
                                      onChange={(option) => updateTableRole(table.index, { list_definition_id: option.id })}
                                    />
                                  ) : current.role === "matrix" ? (
                                    <select
                                      value={current.matrix_key ?? ""}
                                      onChange={(event) => updateTableRole(table.index, { matrix_key: event.target.value || null })}
                                    >
                                      <option value="">– auswählen –</option>
                                      {analysis.matrix_options.map((option) => (
                                        <option key={option.matrix_key} value={option.matrix_key}>
                                          {option.title}
                                        </option>
                                      ))}
                                    </select>
                                  ) : (
                                    <span className="muted">—</span>
                                  )}
                                  {isPending && <SpinnerIcon size={12} />}
                                </span>
                              </td>
                              <td>
                                {current.role === "list" ? (
                                  <div className="grid" style={{ gap: "4px" }}>
                                    <select
                                      className={table.needs_manual_grouping ? "word-import-select-warning" : undefined}
                                      value={current.list_grouping_strategy ?? ""}
                                      onChange={(event) =>
                                        updateTableRole(table.index, {
                                          list_grouping_strategy: (event.target.value || null) as ListGroupingStrategy | null,
                                        })
                                      }
                                    >
                                      <option value="">Automatisch</option>
                                      {table.available_grouping_strategies.map((strategy) => (
                                        <option key={strategy} value={strategy}>
                                          {listGroupingStrategyLabel(strategy)}
                                        </option>
                                      ))}
                                    </select>
                                    {table.needs_manual_grouping && !current.list_grouping_strategy && (
                                      <span className="muted" style={{ fontSize: "0.8em" }}>
                                        Liste ist noch leer – bitte Gruppierung prüfen und ggf. anpassen.
                                      </span>
                                    )}
                                  </div>
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

              {activeCategory === "names" && (
                <>
                  <div>
                    <h3 className="word-import-panel-title">Namen klären</h3>
                    <p className="word-import-panel-desc">
                      Diese Namen kommen mehrfach im Dokument vor und konnten nicht automatisch zugewiesen werden — einmal zuweisen
                      gilt für alle Vorkommen (Anwesenheit, Listen, Matrizen, Texte), statt jede Stelle einzeln zu klären.
                    </p>
                  </div>
                  {recurringNameGroups.length === 0 ? (
                    <p className="muted">Keine wiederkehrenden, ungeklärten Namen gefunden.</p>
                  ) : (
                    <div className="grid" style={{ gap: "10px" }}>
                      {recurringNameGroups.map((group) => {
                        const whereParts: string[] = [];
                        if (group.counts.attendance) whereParts.push(`${group.counts.attendance}× Anwesenheit`);
                        if (group.counts.list) whereParts.push(`${group.counts.list}× Liste`);
                        if (group.counts.matrix) whereParts.push(`${group.counts.matrix}× Matrix`);
                        if (group.counts.text) whereParts.push(`${group.counts.text}× Text`);
                        const menuOptions: AssigneeOption[] = [
                          { id: CREATE_NEW_PARTICIPANT_ID, display_name: `🆕 Als neuen Teilnehmer anlegen: "${group.label}"` },
                          ...participants,
                        ];
                        return (
                          <div className="word-import-text-row word-import-flag" key={group.key}>
                            <div className="word-import-text-row-head">
                              <span className="word-import-text-row-title">
                                {group.label}{" "}
                                <span className="muted" style={{ fontWeight: 400 }}>
                                  · {group.total}× im Dokument ({whereParts.join(", ")})
                                </span>
                              </span>
                            </div>
                            {group.candidates.length > 0 && (
                              <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
                                {group.candidates.map((candidate) => {
                                  const candidateParticipant = participants.find((p) => p.id === candidate.participant_id);
                                  if (!candidateParticipant) return null;
                                  return (
                                    <button
                                      key={candidate.participant_id}
                                      type="button"
                                      className="word-import-decision-btn is-take"
                                      onClick={() => applyRecurringNameEverywhere(group.key, candidate.participant_id)}
                                    >
                                      <CheckIcon /> {candidateParticipant.display_name} ({Math.round(candidate.score * 100)}%)
                                    </button>
                                  );
                                })}
                              </div>
                            )}
                            <div style={{ display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap" }}>
                              <TodoAssigneeMenu
                                label="Anderen Teilnehmer wählen…"
                                nullLabel="Keinen verknüpfen (überall)"
                                activeId={null}
                                participants={menuOptions}
                                onChange={(option) => applyRecurringNameEverywhere(group.key, option.id)}
                              />
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </>
              )}

              {activeCategory === "attendance" && (
                <>
                  <div>
                    <h3 className="word-import-panel-title">Anwesenheit</h3>
                    <p className="word-import-panel-desc">{attendance.length} Namen im Dokument erkannt.</p>
                  </div>
                  <div className="grid" style={{ gap: "10px" }}>
                    {attendance.map((entry, index) => renderAttendanceRow(entry, index))}
                    {attendance.length === 0 && <p className="muted">Keine Anwesenheitstabelle erkannt bzw. zugeordnet.</p>}
                  </div>
                </>
              )}

              {activeCategory === "events" && (
                <>
                  <div>
                    <h3 className="word-import-panel-title">Termine</h3>
                    <p className="word-import-panel-desc">Im Dokument erwähnte Anlässe mit bestehenden Terminen abgleichen.</p>
                  </div>
                  <div className="grid" style={{ gap: "10px" }}>
                    {plainEventItems.map(({ entry, index }) => renderEventRow(entry, index))}
                    {plainEventItems.length === 0 && <p className="muted">Keine Termin-Tabelle erkannt bzw. zugeordnet.</p>}
                  </div>
                </>
              )}

              {activeCategory === "lists" && (
                <>
                  <div>
                    <h3 className="word-import-panel-title">Listen</h3>
                    <p className="word-import-panel-desc">Erkannte Listen-Zeilen bestehenden Einträgen zuordnen.</p>
                  </div>
                  <div className="grid" style={{ gap: "10px" }}>
                    {lists.map((entry, index) => renderListRow(entry, index))}
                    {lists.length === 0 && <p className="muted">Keine Listen-Tabelle erkannt bzw. zugeordnet.</p>}
                  </div>
                </>
              )}

              {activeCategory === "matrices" && (
                <>
                  <div>
                    <h3 className="word-import-panel-title">Matrizen</h3>
                    <p className="word-import-panel-desc">Erkannte Matrix-Daten je Spalte, wie im Protokoll-Editor.</p>
                  </div>
                  <div className="grid" style={{ gap: "20px" }}>
                    {matrixCardGroups.map((group) => (
                      <div key={group.matrixKey} className="grid" style={{ gap: "8px" }}>
                        <strong>{group.matrixTitle}</strong>
                        <div className="matrix-cards matrix-cards-stacked">
                          {group.columns.map((column) => {
                            const resolvedLabel = column.columnKey
                              ? column.candidates.find((candidate) => candidate.column_key === column.columnKey)?.label ??
                                column.columnLabelRaw
                              : null;
                            return (
                              <div className="matrix-card" key={`${group.matrixKey}-${column.columnLabelRaw}`}>
                                <div className="matrix-card-header">
                                  <span className="matrix-card-title">
                                    {column.columnKey ? <CheckIcon /> : <WarningIcon />} {resolvedLabel ?? column.columnLabelRaw}
                                  </span>
                                </div>
                                {column.columnKey === null && (
                                  <div className="matrix-card-row">
                                    <div className="matrix-card-row-label">Ziel-Spalte</div>
                                    <div className="matrix-card-row-cell">
                                      <select
                                        value=""
                                        onChange={(event) => {
                                          const value = event.target.value;
                                          if (!value) return;
                                          resolveMatrixColumn(group.matrixKey, column.columnLabelRaw, value);
                                        }}
                                      >
                                        <option value="">– auswählen ({column.columnLabelRaw}) –</option>
                                        {column.candidates.map((candidate) => (
                                          <option key={candidate.column_key} value={candidate.column_key}>
                                            {candidate.label}
                                          </option>
                                        ))}
                                      </select>
                                    </div>
                                  </div>
                                )}
                                {column.rows.map((row) => {
                                  if (row.kind !== "cell") {
                                    return (
                                      <div className="matrix-card-row" key={`events-${row.rowId}`}>
                                        <div className="matrix-card-row-label">{row.rowLabel}</div>
                                        <div className="matrix-card-row-cell">
                                          <div className="matrix-event-list">
                                            {row.items.map(({ entry, index }) => renderEventRow(entry, index))}
                                            {row.items.length === 0 && <span className="muted">Keine Termine</span>}
                                          </div>
                                        </div>
                                      </div>
                                    );
                                  }
                                  const cellFlagged = matrixNeedsReview(row.entry);
                                  const cellDecision = decisionState(row.entry.approved, cellFlagged);
                                  return (
                                    <div
                                      className={`matrix-card-row${cellDecision === "ignore" ? " matrix-card-row-muted" : ""}`}
                                      key={`cell-${row.index}`}
                                    >
                                      <div className="matrix-card-row-label">{row.entry.row_label}</div>
                                      <div className="matrix-card-row-cell">
                                        {NAME_COLUMN_TYPES.has(row.entry.row_type) && row.entry.names.length > 0 ? (
                                          <div className="grid" style={{ gap: "0.35rem" }}>
                                            {row.entry.names.map((name, nameIndex) => (
                                              <div key={nameIndex} className="field-stack">
                                                <span className="muted">{name.raw_name}</span>
                                                <TodoAssigneeMenu
                                                  label={
                                                    participants.find((participant) => participant.id === name.participant_id)
                                                      ?.display_name ?? "Keinen verknüpfen"
                                                  }
                                                  nullLabel="Keinen verknüpfen"
                                                  activeId={name.participant_id}
                                                  participants={participants}
                                                  onChange={(option) => updateMatrixName(row.index, nameIndex, option.id)}
                                                />
                                              </div>
                                            ))}
                                          </div>
                                        ) : (
                                          <span className="matrix-static-value">{row.entry.raw_value || "–"}</span>
                                        )}
                                        <div style={{ display: "flex", justifyContent: "flex-end" }}>
                                          <button
                                            type="button"
                                            className={`word-import-decision-btn is-${cellDecision}`}
                                            onClick={() => {
                                              const patch = nextDecisionPatch(cellDecision);
                                              // A cell whose column was never resolved has no
                                              // column_key to write to at commit time -
                                              // submitCommit's approvedMatrices filter already
                                              // drops such a cell even if "approved" here, so
                                              // letting the pill reach "Übernehmen" anyway just
                                              // shows a false confirmation for a cell that gets
                                              // silently discarded (real bug fixed here, same
                                              // shape as the dateless-Termin guard above).
                                              if (patch.approved && row.entry.column_key === null) return;
                                              setMatrices((current) =>
                                                current.map((item, itemIndex) =>
                                                  itemIndex === row.index ? { ...item, ...patch } : item
                                                )
                                              );
                                            }}
                                          >
                                            <CheckIcon /> {DECISION_LABEL[cellDecision]}
                                          </button>
                                        </div>
                                      </div>
                                    </div>
                                  );
                                })}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    ))}
                    {matrixCardGroups.length === 0 && <p className="muted">Keine Matrix-Tabelle erkannt bzw. zugeordnet.</p>}
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
                      const isIgnoredEvent = text.isEventRepeat && text.linkedEventId === null && text.linkedEventNone;
                      // A section with no matching template block at all, or a form block
                      // with a name that couldn't be auto-matched, has nothing else to decide
                      // (unlike the event-repeat case above, which already has its own "nicht
                      // verknüpfen" option) - offer the same explicit dismiss here so it
                      // doesn't stay flagged forever with no way out. Dismissing skips the
                      // WHOLE section, same row-level granularity Liste/Matrix rows already
                      // use for an unresolved name.
                      const isIgnorableNoTarget = text.template_element_id === null;
                      const canDismiss = isIgnorableNoTarget || formFieldsStillOpen(text);
                      const isDismissedNoTarget = canDismiss && text.dismissed;
                      const summaryLabel = textSummaryLabel(text, target, linkedEvent);
                      return (
                        <div
                          className={`word-import-text-row${flagged ? " word-import-flag" : ""}${
                            isIgnoredEvent || isDismissedNoTarget ? " word-import-text-row-muted" : ""
                          }`}
                          key={index}
                        >
                          <div
                            className={`word-import-text-row-head${flagged ? "" : " word-import-text-row-head-clickable"}`}
                            role={flagged ? undefined : "button"}
                            tabIndex={flagged ? undefined : 0}
                            onClick={() => !flagged && toggleTextExpanded(index)}
                            onKeyDown={flagged ? undefined : rowHeadKeyDown(() => toggleTextExpanded(index))}
                          >
                            <span className="word-import-text-row-title">{text.extracted_heading}</span>
                            <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                              {!isOpen &&
                                (isIgnoredEvent ? (
                                  <span className="word-import-text-row-summary is-ignored">Nicht verknüpft – wird übersprungen</span>
                                ) : isDismissedNoTarget ? (
                                  <span className="word-import-text-row-summary is-ignored">Ignoriert – wird übersprungen</span>
                                ) : summaryLabel ? (
                                  <span className="word-import-text-row-summary">
                                    <CheckIcon /> {summaryLabel}
                                  </span>
                                ) : (
                                  <span className="word-import-text-row-summary is-unassigned">– nicht zugewiesen –</span>
                                ))}
                              {canDismiss && (
                                <button
                                  type="button"
                                  className={`word-import-decision-btn ${text.dismissed ? "is-ignore" : "is-incomplete"}`}
                                  onClick={(clickEvent) => {
                                    clickEvent.stopPropagation();
                                    setTexts((current) =>
                                      current.map((row, rowIndex) => (rowIndex === index ? { ...row, dismissed: !row.dismissed } : row))
                                    );
                                  }}
                                >
                                  <CheckIcon /> {text.dismissed ? "Ignoriert" : "Ignorieren"}
                                </button>
                              )}
                            </div>
                          </div>
                          {isOpen && (
                            <div className="grid" style={{ gap: "10px" }}>
                              <TodoAssigneeMenu
                                label={
                                  target
                                    ? `${target.label}${target.is_event_repeat ? " · pro Termin" : ""}${target.is_form_block ? " · Formular" : ""}`
                                    : "– nicht zugewiesen –"
                                }
                                nullLabel="– nicht zugewiesen –"
                                activeId={target ? analysis.text_targets.indexOf(target) : null}
                                participants={analysis.text_targets.map(
                                  (candidate, candidateIndex): AssigneeOption => ({
                                    id: candidateIndex,
                                    display_name: `${candidate.label}${candidate.is_event_repeat ? " · pro Termin" : ""}${
                                      candidate.is_form_block ? " · Formular" : ""
                                    }`,
                                  })
                                )}
                                onChange={(option) => {
                                  const nextTarget = option.id === null ? undefined : analysis.text_targets[option.id];
                                  const templateElementId = nextTarget?.template_element_id ?? null;
                                  const blockSortIndex = nextTarget?.block_sort_index ?? null;
                                  setTexts((current) =>
                                    current.map((row, rowIndex) =>
                                      rowIndex === index
                                        ? {
                                            ...row,
                                            template_element_id: templateElementId,
                                            block_sort_index: blockSortIndex,
                                            isEventRepeat: nextTarget?.is_event_repeat ?? false,
                                            linkedEventId: nextTarget?.is_event_repeat ? row.linkedEventId : null,
                                            linkedEventNone: nextTarget?.is_event_repeat ? row.linkedEventNone : false,
                                            dismissed: false,
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
                              />
                              {text.isEventRepeat && (
                                <label className="field-stack" style={{ gap: "0.25rem" }}>
                                  <span className="muted">Aufgrund welchem Termin wird dieser Block erstellt?</span>
                                  <TodoAssigneeMenu
                                    label={linkedEvent ? `${linkedEvent.title} (${formatDate(linkedEvent.event_date)})` : "– Anlass wählen –"}
                                    nullLabel="– nicht verknüpfen (Text wird nicht übernommen) –"
                                    activeId={text.linkedEventId}
                                    participants={text.eventCandidates.map(
                                      (candidate): AssigneeOption => ({
                                        id: candidate.event_id,
                                        display_name: `${candidate.title} (${formatDate(candidate.event_date)})`,
                                      })
                                    )}
                                    onChange={(option) =>
                                      setTexts((current) =>
                                        current.map((row, rowIndex) =>
                                          rowIndex === index
                                            ? { ...row, linkedEventId: option.id, linkedEventNone: option.id === null }
                                            : row
                                        )
                                      )
                                    }
                                  />
                                </label>
                              )}
                              {text.syncTargetField && (
                                <div
                                  className={
                                    text.syncFieldStatus === "conflict"
                                      ? "word-import-alert word-import-alert-block"
                                      : "word-import-alert word-import-alert-block word-import-alert-neutral"
                                  }
                                >
                                  {text.syncFieldStatus === "conflict" ? <WarningIcon /> : <LinkIcon />}
                                  <div className="grid" style={{ gap: "10px" }}>
                                    {text.syncFieldStatus === "conflict" ? (
                                      <>
                                        <span>
                                          Das Feld &quot;{EVENT_SYNC_FIELD_LABELS[text.syncTargetField] ?? text.syncTargetField}&quot; des
                                          verknüpften Termins enthält bereits einen abweichenden Wert. Welcher Wert soll übernommen werden?
                                        </span>
                                        <div className="word-import-diff-options">
                                          <label className="field-radio-option">
                                            <input
                                              type="radio"
                                              checked={text.syncFieldSource === "doc"}
                                              onChange={() =>
                                                setTexts((current) =>
                                                  current.map((row, rowIndex) => (rowIndex === index ? { ...row, syncFieldSource: "doc" } : row))
                                                )
                                              }
                                            />
                                            <span>
                                              <span className="field-radio-option-label">Aus Dokument</span>
                                              <strong>{text.content}</strong>
                                            </span>
                                          </label>
                                          <label className="field-radio-option">
                                            <input
                                              type="radio"
                                              checked={text.syncFieldSource === "existing"}
                                              onChange={() =>
                                                setTexts((current) =>
                                                  current.map((row, rowIndex) =>
                                                    rowIndex === index ? { ...row, syncFieldSource: "existing" } : row
                                                  )
                                                )
                                              }
                                            />
                                            <span>
                                              <span className="field-radio-option-label">Bestehend</span>
                                              <strong>{text.syncFieldExistingValue}</strong>
                                            </span>
                                          </label>
                                        </div>
                                      </>
                                    ) : text.syncFieldStatus === "match" ? (
                                      <span>
                                        Dieser Text wird außerdem in das Feld &quot;{EVENT_SYNC_FIELD_LABELS[text.syncTargetField] ?? text.syncTargetField}
                                        &quot; des verknüpften Termins geschrieben – der dortige Wert stimmt bereits damit überein.
                                      </span>
                                    ) : (
                                      <span>
                                        Dieser Text wird außerdem in das Feld &quot;{EVENT_SYNC_FIELD_LABELS[text.syncTargetField] ?? text.syncTargetField}
                                        &quot; des verknüpften Termins übernommen (dort aktuell leer).
                                      </span>
                                    )}
                                  </div>
                                </div>
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
                                        <div className="field-stack" style={{ gap: "0.15rem" }}>
                                          {field.raw_value && field.names[0]?.participant_id === null && !field.names[0]?.create_new && (
                                            <span className="muted">{field.raw_value}</span>
                                          )}
                                          <TodoAssigneeMenu
                                            label={
                                              field.names[0]?.create_new
                                                ? `🆕 Neuer Teilnehmer: "${field.names[0].raw_name}"`
                                                : participants.find((participant) => participant.id === field.names[0]?.participant_id)?.display_name ??
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
                                        </div>
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
              <span className="word-import-footer-warning">
                {totalOpen} {totalOpen === 1 ? "Warnung" : "Warnungen"} noch offen — erst wenn alle geprüft sind, kann das Protokoll
                erstellt werden.
              </span>
            ) : (
              <span />
            )}
            <div className="wizard-footer-actions">
              <button
                type="button"
                className="button-ghost"
                onClick={() => (documentId ? onExitQueueMode?.() : setStep("upload"))}
              >
                {documentId ? "Zurück zur Warteschlange" : "Abbrechen"}
              </button>
              {step === "review" && (
                <button
                  type="button"
                  className="button-primary"
                  disabled={busy || !protocolDate || totalOpen > 0}
                  onClick={() => void submitCommit()}
                >
                  {busy ? "…" : "Protokoll erstellen"}
                </button>
              )}
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
                  `${doneSummary.attendance} Anwesenheiten, ${doneSummary.events} Termine, ${doneSummary.lists} Listeneinträge und ${doneSummary.matrices} Matrix-Werte wurden übernommen.`}
                {doneSummary && doneSummary.skipped > 0 && (
                  <> {doneSummary.skipped} Einträge wurden übersprungen und können manuell nachgetragen werden.</>
                )}
              </p>
              {doneSummary && doneSummary.warnings.length > 0 && (
                <div className="word-import-alert word-import-alert-block" style={{ marginTop: "10px" }}>
                  <WarningIcon />
                  <ul style={{ margin: 0, paddingLeft: "18px" }}>
                    {doneSummary.warnings.map((warning, index) => (
                      <li key={index}>{warning}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>
          <div className="wizard-footer">
            <button
              type="button"
              className="button-ghost"
              onClick={() => (documentId ? onExitQueueMode?.() : resetWizard())}
            >
              {documentId ? "Zurück zur Warteschlange" : "Neuer Import"}
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
