"use client";

import { useEffect, useRef, useState } from "react";
import { Badge, BadgeVariant } from "@/components/ui/badge";
import { PillMenu } from "@/components/ui/pill-menu";
import { ATTENDANCE_OPTIONS } from "@/components/protocol/protocol-editor-shared";
import { AssigneeOption, TodoAssigneeMenu } from "@/components/todos/todo-assignee-menu";
import { browserApiFetch } from "@/lib/api/client";
import { formatDate } from "@/lib/utils/format";
import {
  analyzeWordImport,
  commitWordImport,
  commitWordImportDocument,
  EventMatchStatus,
  getWordImportDocument,
  ListRowStatus,
  reanalyzeWordImportDocument,
  saveWordImportDocumentDraft,
  TableRole,
  TableRoleOverride,
  WordImportAnalysis,
  WordImportEventCandidate,
  WordImportFormFieldValue,
  WordImportListEntryCandidate,
  WordImportMatrixColumnCandidate,
  WordImportNameResolution,
  WordImportReviewDraftJson,
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
  { value: "matrix", label: "Matrix" },
];

const TABLE_ROLE_PILL_OPTIONS = TABLE_ROLE_OPTIONS.map((option) => ({
  ...option,
  variant: roleBadgeVariant(option.value),
}));

const ATTENDANCE_PILL_OPTIONS = ATTENDANCE_OPTIONS.map((option) => ({
  ...option,
  variant: statusPillVariant(option.value),
}));

const APPROVE_PILL_OPTIONS: { value: "take" | "ignore"; label: string; variant: BadgeVariant }[] = [
  { value: "take", label: "Übernehmen", variant: "success" },
  { value: "ignore", label: "Ignorieren", variant: "neutral" },
];

type Category = "tables" | "attendance" | "events" | "lists" | "matrices" | "texts";

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

const CATEGORIES: { key: Category; label: string; Icon: typeof TableIcon }[] = [
  { key: "tables", label: "Tabellen", Icon: TableIcon },
  { key: "attendance", label: "Anwesenheit", Icon: PeopleIcon },
  { key: "events", label: "Termine", Icon: CalendarIcon },
  { key: "lists", label: "Listen", Icon: ListIcon },
  { key: "matrices", label: "Matrizen", Icon: MatrixIcon },
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
  isFormBlock: boolean;
  formFields: WordImportFormFieldValue[];
  formFieldsByTarget: Record<string, WordImportFormFieldValue[]>;
};
// `linkedNone` records that the user explicitly chose "Keinen verknüpfen" - without it,
// that choice is indistinguishable from "not yet decided" (both leave participant_id null),
// so the row would stay flagged as needing review forever.
type AttendanceDraft = { raw_name: string; status: string; participant_id: number | null; createNew: boolean; linkedNone: boolean };
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
  // Only set for rows extracted from a Matrix "events" row - see WordImportEventMapping.
  tag: string | null;
  participant_count: number | null;
  matrix_key: string | null;
  matrix_title: string | null;
  row_id: string | null;
  row_label: string | null;
  column_key: string | null;
  column_label: string | null;
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
};

// Best-effort parse of the opaque JSON blob loaded from the server - only shape-checked
// (right keys, right array-ness), not deeply validated, since it's the same wizard's own
// previously-saved output. Returns null for "no draft yet" (fresh document) as well as for
// anything that doesn't look like a draft at all, so callers can fall back to the freshly
// derived state without special-casing.
function parseReviewDraft(raw: WordImportReviewDraftJson | null | undefined): WordImportReviewDraft | null {
  if (!raw || typeof raw !== "object") return null;
  const { protocolDate, texts, attendance, events, lists, matrices } = raw as Record<string, unknown>;
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
  };
}

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

// A matrix cell needs a decision when its target column couldn't be confidently
// resolved (no column_key yet - the doc header didn't clearly match a template
// column, a real participant, an event, or a list entry), or when a participant/
// participants-typed cell's name(s) couldn't be matched, mirroring listNeedsReview.
function matrixNeedsReview(entry: MatrixDraft): boolean {
  if (entry.column_key === null) return true;
  if (NAME_COLUMN_TYPES.has(entry.row_type)) {
    return entry.names.some((name) => name.participant_id === null);
  }
  return false;
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

function textNeedsReview(text: TextDraft): boolean {
  return text.template_element_id === null || (text.isEventRepeat && text.linkedEventId === null);
}

function attendanceNeedsReview(entry: AttendanceDraft): boolean {
  return entry.participant_id === null && !entry.createNew && !entry.linkedNone;
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
  const [step, setStep] = useState<Step>(documentId ? "review" : "upload");
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
  const [showAllAttendance, setShowAllAttendance] = useState(false);
  const [doneSummary, setDoneSummary] = useState<{ attendance: number; events: number; lists: number; matrices: number; skipped: number } | null>(
    null
  );
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

  function flushDraftSave() {
    const id = documentIdRef.current;
    const draft = pendingDraftRef.current;
    if (!id || !draft) return;
    if (draftTimeoutRef.current) {
      clearTimeout(draftTimeoutRef.current);
      draftTimeoutRef.current = null;
    }
    pendingDraftRef.current = null;
    void saveWordImportDocumentDraft(id, draft as unknown as WordImportReviewDraftJson).catch(() => {});
  }

  useEffect(() => {
    if (!documentId) return;
    if (isHydratingRef.current) {
      isHydratingRef.current = false;
      return;
    }
    pendingDraftRef.current = { protocolDate, texts, attendance, events, lists, matrices };
    draftTimeoutRef.current = setTimeout(flushDraftSave, 800);
    return () => {
      if (draftTimeoutRef.current) clearTimeout(draftTimeoutRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentId, protocolDate, texts, attendance, events, lists, matrices]);

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
        applyAnalysis(detail.analysis, parseReviewDraft(detail.review_draft));
        setStep("review");
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Dokument konnte nicht geladen werden"))
      .finally(() => setBusy(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentId]);

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

  function updateEventAt(index: number, patch: Partial<EventDraft>) {
    setEvents((current) => current.map((row, rowIndex) => (rowIndex === index ? { ...row, ...patch } : row)));
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
    const hasDiff = eventNeedsReview(entry);
    const isOpen = expandedEvents.has(index);
    const titleDiffers = !!linked && linked.title !== entry.raw_title;
    const dateDiffers = !!linked && linked.event_date !== (entry.raw_date ?? linked.event_date);
    return (
      <div className={`word-import-text-row${hasDiff ? " word-import-flag" : ""}`} key={entry.row_index}>
        <div className="word-import-text-row-head" style={{ cursor: "pointer" }} onClick={() => toggleEventExpanded(index)}>
          <span className="word-import-text-row-title">
            {entry.raw_title} ({formatDate(entry.raw_date) || "?"})
            {entry.participant_count !== null && <span className="muted"> · {entry.participant_count} TN</span>}
          </span>
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            {!isOpen &&
              (linked ? (
                <span className="word-import-text-row-summary">
                  <CheckIcon /> {linked.title} ({formatDate(linked.event_date)})
                </span>
              ) : (
                <span className="word-import-text-row-summary is-new">
                  <PlusIcon /> Neu anlegen
                </span>
              ))}
            <div className="word-import-decision-group">
              <button
                type="button"
                className={`word-import-decision-btn is-take${entry.approved ? " is-active" : ""}`}
                onClick={(clickEvent) => {
                  clickEvent.stopPropagation();
                  updateEventAt(index, { approved: true });
                }}
              >
                {entry.approved && <CheckIcon />} Übernehmen
              </button>
              <button
                type="button"
                className={`word-import-decision-btn is-ignore${!entry.approved ? " is-active" : ""}`}
                onClick={(clickEvent) => {
                  clickEvent.stopPropagation();
                  updateEventAt(index, { approved: false });
                }}
              >
                {!entry.approved && <CheckIcon />} Ignorieren
              </button>
            </div>
          </div>
        </div>
        {isOpen && (
          <div className="grid" style={{ gap: "10px" }}>
            <TodoAssigneeMenu
              label={linked ? `${linked.title} (${formatDate(linked.event_date)})` : "🆕 Neu anlegen"}
              nullLabel="🆕 Neu anlegen"
              activeId={entry.linked_event_id}
              participants={entry.candidates.map(
                (candidate): AssigneeOption => ({
                  id: candidate.event_id,
                  display_name: `${candidate.title} (${formatDate(candidate.event_date)})`,
                })
              )}
              onChange={(option) =>
                updateEventAt(index, { linked_event_id: option.id, title_source: "existing", date_source: "existing" })
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
                          onChange={() => updateEventAt(index, { title_source: "doc" })}
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
                          onChange={() => updateEventAt(index, { title_source: "existing" })}
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
                          onChange={() => updateEventAt(index, { date_source: "doc" })}
                        />
                        <span>
                          <span className="field-radio-option-label">Aus Dokument</span>
                          <strong>{formatDate(entry.raw_date) || "?"}</strong>
                        </span>
                      </label>
                      <label className="field-radio-option">
                        <input
                          type="radio"
                          checked={entry.date_source === "existing"}
                          onChange={() => updateEventAt(index, { date_source: "existing" })}
                        />
                        <span>
                          <span className="field-radio-option-label">Bestehend</span>
                          <strong>{formatDate(linked.event_date)}</strong>
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

  function applyAnalysis(result: WordImportAnalysis, draft?: WordImportReviewDraft | null) {
    // Suppresses the draft-autosave effect for the state update this triggers - loading or
    // reanalyzing a document isn't itself a reviewer edit worth saving back.
    isHydratingRef.current = true;
    setAnalysis(result);
    setProtocolDate(draft ? draft.protocolDate : result.protocol_date ?? "");
    setTableRoles(
      Object.fromEntries(
        result.tables.map((table) => [
          table.index,
          { role: table.role, list_definition_id: table.list_definition_id, matrix_key: table.matrix_key },
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
      isFormBlock: mapping.is_form_block,
      formFields: mapping.form_fields,
      formFieldsByTarget: mapping.form_fields_by_target,
    }));
    const freshAttendance: AttendanceDraft[] = result.attendance_mappings.map((mapping) => ({
      raw_name: mapping.raw_name,
      status: mapping.status,
      participant_id: mapping.suggested_participant_id,
      createNew: false,
      linkedNone: false,
    }));
    const freshEvents: EventDraft[] = result.event_mappings.map((mapping) => ({
      row_index: mapping.row_index,
      raw_title: mapping.raw_title,
      raw_date: mapping.raw_date,
      status: mapping.status,
      candidates: mapping.candidates,
      linked_event_id: mapping.status !== "new" ? mapping.matched_event_id : null,
      title_source: "existing",
      date_source: "existing",
      approved: mapping.status === "matched",
      tag: mapping.tag,
      participant_count: mapping.participant_count,
      matrix_key: mapping.matrix_key,
      matrix_title: mapping.matrix_title,
      row_id: mapping.row_id,
      row_label: mapping.row_label,
      column_key: mapping.column_key,
      column_label: mapping.column_label,
    }));
    const freshLists: ListDraft[] = result.list_mappings.map((mapping) => ({
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
      approved: mapping.status === "matched" && mapping.has_snapshot_target,
    }));
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
    }));
    // A saved draft is only applied per-category when its row count still matches the
    // freshly derived one - a mismatch means the underlying document was reanalyzed since
    // the draft was saved (new/removed rows), so the draft's indices no longer line up and
    // falling back to the fresh suggestions is safer than silently misapplying old edits.
    const eventsToUse = draft && draft.events.length === freshEvents.length ? draft.events : freshEvents;
    setTexts(draft && draft.texts.length === freshTexts.length ? draft.texts : freshTexts);
    setAttendance(draft && draft.attendance.length === freshAttendance.length ? draft.attendance : freshAttendance);
    setEvents(eventsToUse);
    setLists(draft && draft.lists.length === freshLists.length ? draft.lists : freshLists);
    setMatrices(draft && draft.matrices.length === freshMatrices.length ? draft.matrices : freshMatrices);
    setActiveCategory("tables");
    setExpandedTexts(new Set());
    setExpandedEvents(new Set());
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

  async function reanalyzeWithRoles(nextTableRoles: Record<number, TableRoleOverride>) {
    if (!templateId) return;
    if (!documentId && !file) return;
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
    }
  }

  // Reassigning a table's role (e.g. "Liste"/"Matrix"/Ziel) changes how its rows must be
  // interpreted, so it has to go back through the server-side parser rather than just
  // updating local state - otherwise the attendance/events/lists/matrices tabs would keep
  // showing stale rows derived from the table's previous role.
  function updateTableRole(tableIndex: number, patch: Partial<TableRoleOverride>) {
    if (busy) return;
    const current = tableRoles[tableIndex] ?? { role: "ignore" as TableRole, list_definition_id: null, matrix_key: null };
    setPendingTableIndex(tableIndex);
    void reanalyzeWithRoles({ ...tableRoles, [tableIndex]: { ...current, ...patch } });
  }

  async function reanalyze() {
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

  function updateMatrixName(rowIndex: number, nameIndex: number, participantId: number | null) {
    setMatrices((current) =>
      current.map((row, index) => {
        if (index !== rowIndex) return row;
        const updatedNames = row.names.map((name, i) => (i === nameIndex ? { ...name, participant_id: participantId } : name));
        return { ...row, names: updatedNames, approved: true };
      })
    );
  }

  // Picking a column in the card header must resolve EVERY cell sharing that same
  // (matrix, doc column) - not just one row - since the backend computes column
  // resolution once per table, shared across all its rows (see column_resolution in
  // WordImportService.analyze).
  function resolveMatrixColumn(matrixKey: string, columnLabelRaw: string, columnKey: string) {
    setMatrices((current) =>
      current.map((row) =>
        row.matrix_key === matrixKey && row.column_label_raw === columnLabelRaw ? { ...row, column_key: columnKey, approved: true } : row
      )
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
            tag: entry.tag,
            participant_count: entry.participant_count,
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
        })),
        tables: analysis.tables.map((table) => ({
          header_signature: normalizeHeaderSignature(table.header_cells),
          role: tableRoles[table.index]?.role ?? table.role,
          list_definition_id: tableRoles[table.index]?.list_definition_id ?? table.list_definition_id,
          matrix_key: tableRoles[table.index]?.matrix_key ?? table.matrix_key,
        })),
      };
      const result = documentId ? await commitWordImportDocument(documentId, payload) : await commitWordImport(payload);
      setDoneSummary({
        attendance: approvedAttendance.length,
        events: approvedEvents.length,
        lists: approvedLists.length,
        matrices: approvedMatrices.length,
        skipped:
          attendance.length -
          approvedAttendance.length +
          (events.length - approvedEvents.length) +
          (lists.filter((entry) => entry.has_snapshot_target).length - approvedLists.length) +
          (matrices.length - approvedMatrices.length) +
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

  const categoryCounts: Record<Category, number> = {
    tables: analysis?.tables.length ?? 0,
    attendance: attendanceOpen,
    events: eventsOpen,
    lists: listsOpen,
    matrices: matricesOpen,
    texts: textsOpen,
  };
  const categoryVariants: Record<Category, BadgeVariant> = {
    tables: "neutral",
    attendance: "warning",
    events: "warning",
    lists: "warning",
    matrices: "warning",
    texts: "warning",
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

      {step === "review" && !analysis && busy && <p className="muted">Dokument wird geladen…</p>}

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

      {step === "review" && analysis && (
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
                          // A participant already linked to a different row that was actually
                          // found in the document may not be picked again here - that would
                          // silently link the same person twice. Rows with no raw_name are the
                          // "not found in document, defaults to absent" placeholders (see
                          // applyAnalysis/attendance onChange below) and are deliberately excluded
                          // from this check: reassigning one of those participants to a real
                          // document row is exactly how such a placeholder gets resolved.
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
                            <tr key={index} className={attendanceNeedsReview(entry) ? "table-row-error" : undefined}>
                              <td>{entry.raw_name || <span className="muted">– nicht im Dokument (Standard: abwesend) –</span>}</td>
                              <td>
                                <PillMenu
                                  value={entry.status}
                                  options={ATTENDANCE_PILL_OPTIONS}
                                  onChange={(status) =>
                                    setAttendance((current) =>
                                      current.map((row, rowIndex) => (rowIndex === index ? { ...row, status } : row))
                                    )
                                  }
                                />
                              </td>
                              <td>
                                {attendanceNeedsReview(entry) ? (
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
                                        // Linking this document row to a participant who was only
                                        // present as a "not found in document" placeholder (see
                                        // applyAnalysis) makes that placeholder row redundant - drop
                                        // it, otherwise the participant would be submitted twice.
                                        if (option.id === null || option.id === CREATE_NEW_PARTICIPANT_ID) return updated;
                                        return updated.filter(
                                          (row, rowIndex) => rowIndex === index || !(row.raw_name === "" && row.participant_id === option.id)
                                        );
                                      })
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
                                  {needsReview ? (
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
                                  ) : linked ? (
                                    <span className="word-import-text-row-summary">
                                      <CheckIcon /> {linked.column_one_display} → {linked.column_two_display}
                                    </span>
                                  ) : (
                                    <span className="word-import-text-row-summary is-new">
                                      <PlusIcon /> Neu (nur in diesem Protokoll)
                                    </span>
                                  )}
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
                                  <PillMenu
                                    value={entry.approved ? "take" : "ignore"}
                                    options={APPROVE_PILL_OPTIONS}
                                    onChange={(value) =>
                                      setLists((current) =>
                                        current.map((row, rowIndex) => (rowIndex === index ? { ...row, approved: value === "take" } : row))
                                      )
                                    }
                                  />
                                </td>
                              </tr>
                              {linked && col2Differs && col2IsText && (
                                <tr key={`${entry.table_index}-${entry.row_index}-diff`}>
                                  <td colSpan={5} className="word-import-diff-cell">
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
                                                  current.map((row, rowIndex) =>
                                                    rowIndex === index ? { ...row, column_two_source: "existing" } : row
                                                  )
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
                        <div className="matrix-cards">
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
                                {column.rows.map((row) =>
                                  row.kind === "cell" ? (
                                    <div className="matrix-card-row" key={`cell-${row.index}`}>
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
                                          <PillMenu
                                            value={row.entry.approved ? "take" : "ignore"}
                                            options={APPROVE_PILL_OPTIONS}
                                            onChange={(value) =>
                                              setMatrices((current) =>
                                                current.map((item, itemIndex) =>
                                                  itemIndex === row.index ? { ...item, approved: value === "take" } : item
                                                )
                                              )
                                            }
                                          />
                                        </div>
                                      </div>
                                    </div>
                                  ) : (
                                    <div className="matrix-card-row" key={`events-${row.rowId}`}>
                                      <div className="matrix-card-row-label">{row.rowLabel}</div>
                                      <div className="matrix-card-row-cell">
                                        <div className="matrix-event-list">
                                          {row.items.map(({ entry, index }) => renderEventRow(entry, index))}
                                          {row.items.length === 0 && <span className="muted">Keine Termine</span>}
                                        </div>
                                      </div>
                                    </div>
                                  )
                                )}
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
              <button
                type="button"
                className="button-ghost"
                onClick={() => (documentId ? onExitQueueMode?.() : setStep("upload"))}
              >
                {documentId ? "Zurück zur Warteschlange" : "Abbrechen"}
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
                  `${doneSummary.attendance} Anwesenheiten, ${doneSummary.events} Termine, ${doneSummary.lists} Listeneinträge und ${doneSummary.matrices} Matrix-Werte wurden übernommen.`}
                {doneSummary && doneSummary.skipped > 0 && (
                  <> {doneSummary.skipped} Einträge wurden übersprungen und können manuell nachgetragen werden.</>
                )}
              </p>
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
