import { browserApiFetch } from "@/lib/api/client";

export type TableRole = "attendance" | "events" | "list" | "matrix" | "ignore";
export type EventMatchStatus = "matched" | "changed" | "new";
export type ListRowStatus = "matched" | "changed" | "new";

// "flat" | "fill_down" | "swap", or an exploded split keyed
// "explode:<delimiter>"/"explode_swap:<delimiter>" where delimiter is one of
// "comma"/"semicolon"/"slash"/"newline"/"space" - which delimiters actually appear is
// data-dependent, so this is a plain string rather than a fixed union; see
// TablePreview.available_grouping_strategies for the real, per-table option set.
export type ListGroupingStrategy = string;

export type TablePreview = {
  index: number;
  header_cells: string[];
  sample_rows: string[][];
  role: TableRole;
  list_definition_id: number | null;
  matrix_key: string | null;
  has_snapshot_target: boolean;
  grouping_strategy: ListGroupingStrategy | null;
  needs_manual_grouping: boolean;
  // Every grouping_strategy value the server actually produced for this table's real
  // data (see word_import.py TablePreview docstring) - the wizard's manual picker
  // must only ever offer entries from this list.
  available_grouping_strategies: ListGroupingStrategy[];
  // True when `role` came from an explicit source (manual override or a learned
  // profile signature match) rather than a heuristic guess - used by the import
  // queue's batch consensus to decide which tables are confident enough to vote on.
  role_is_explicit: boolean;
};

export type WordImportNameResolution = {
  raw_name: string;
  participant_id: number | null;
  create_new: boolean;
  // True when the reviewer explicitly resolved this name as "Keinen verknüpfen" -
  // participant_id stays null either way, so this is what lets buildRecurringNameGroups
  // (and listStillOpen/matrixStillOpen) tell "still needs a decision" apart from
  // "reviewer already decided there's no participant here". See backend
  // WordImportNameResolution.no_link.
  no_link: boolean;
  // What analyze() originally suggested for this name - set once when the resolution
  // is first built, never touched again by our own edit handlers (they only spread-
  // update participant_id), so the backend can tell "still the algorithm's own
  // suggestion" apart from "human picked something else" at commit time.
  originally_suggested_participant_id: number | null;
  originally_suggested_score: number | null;
  // Ranked near-miss alternatives (best first), populated even when nothing cleared
  // the auto-link threshold - see WordImportAttendanceCandidate, reused here so the
  // wizard's recurring-name clarifier can suggest a participant for a name that
  // recurs across many rows without ever having auto-resolved anywhere.
  candidates: WordImportAttendanceCandidate[];
};

export type WordImportFormRow = {
  row_id: string;
  label: string;
  row_type: string;
};

export type WordImportFormFieldValue = {
  row_id: string;
  label: string;
  row_type: string;
  raw_value: string;
  names: WordImportNameResolution[];
};

export type WordImportTextMapping = {
  extracted_heading: string;
  extracted_text: string;
  template_element_id: number | null;
  block_sort_index: number | null;
  confidence: number;
  is_event_repeat: boolean;
  matched_event_id: number | null;
  event_candidates: WordImportEventCandidate[];
  is_form_block: boolean;
  form_fields: WordImportFormFieldValue[];
  // form_fields parsed against every form-block target (keyed by targetKey format
  // "{template_element_id}:{block_sort_index}"), not just the currently matched one -
  // lets the wizard show real parsed values after a manual target switch instead of
  // blank fields.
  form_fields_by_target: Record<string, WordImportFormFieldValue[]>;
};

export type WordImportTextTarget = {
  template_element_id: number;
  block_sort_index: number;
  label: string;
  is_event_repeat: boolean;
  is_form_block: boolean;
  form_rows: WordImportFormRow[];
};

export type WordImportAttendanceCandidate = {
  participant_id: number;
  score: number;
  reason: string;
};

export type WordImportAttendanceMapping = {
  raw_name: string;
  status: string;
  suggested_participant_id: number | null;
  candidates: WordImportAttendanceCandidate[];
  // Set when suggested_participant_id is null AND this exact raw name was already
  // explicitly resolved as "Keinen verknüpfen" in an earlier commit - the wizard
  // pre-applies that same decision instead of re-flagging it every import.
  remembered_no_link: boolean;
};

export type WordImportEventCandidate = {
  event_id: number;
  title: string;
  event_date: string;
  score: number;
  reason: string;
};

export type WordImportEventMapping = {
  row_index: number;
  raw_title: string;
  raw_date: string | null;
  status: EventMatchStatus;
  matched_event_id: number | null;
  matched_event_title: string | null;
  matched_event_date: string | null;
  candidates: WordImportEventCandidate[];
  // Only set for rows extracted from a Matrix "events" row - the tag this Event needs
  // so it shows up in that Matrix column (see WordImportService.analyze). null for
  // ordinary Termine-table rows, whose tag is never touched by the importer.
  tag: string | null;
  // Only set when a trailing "(N)" was found right after the date (e.g. "18.10.2025
  // (7)") - null if the document didn't annotate a count for this date.
  participant_count: number | null;
  // Matrix/row/column context, only set alongside `tag` - lets the wizard group these
  // back into the Matrix's own card layout instead of the flat Termine list.
  matrix_key: string | null;
  matrix_title: string | null;
  row_id: string | null;
  row_label: string | null;
  column_key: string | null;
  column_label: string | null;
  // Set when status === "changed" AND this same (matched event, raw_title) pair already
  // got a resolution decision in an earlier commit - deliberately NOT keyed on raw_date,
  // so a yearly-recurring Termin whose document mention always names a different/stale
  // date still reuses the same decision. The wizard pre-applies it instead of asking the
  // reviewer to reconfirm an already-resolved recurring conflict every import.
  remembered_title_source: "doc" | "existing" | null;
  remembered_date_source: "doc" | "existing" | null;
};

export type WordImportListDefinitionOption = {
  id: number;
  name: string;
};

export type WordImportListEntryCandidate = {
  entry_id: number;
  column_one_display: string;
  column_two_display: string;
  score: number;
  reason: string;
};

export type WordImportListRowMapping = {
  table_index: number;
  row_index: number;
  column_one_raw: string;
  column_two_raw: string;
  column_one_type: string;
  column_two_type: string;
  status: ListRowStatus;
  matched_entry_id: number | null;
  column_one_names: WordImportNameResolution[];
  column_two_names: WordImportNameResolution[];
  candidates: WordImportListEntryCandidate[];
  has_snapshot_target: boolean;
  // True when column_one_raw/column_two_raw's grouping value was inferred
  // (fill-down or repeated across an exploded multi-value cell) rather than
  // literally present in this row's own document cell - worth a second look.
  group_filled: boolean;
};

export type WordImportMatrixOption = {
  matrix_key: string;
  title: string;
};

export type WordImportMatrixColumnCandidate = {
  column_key: string;
  label: string;
  score: number;
  reason: string;
};

export type WordImportMatrixCellMapping = {
  table_index: number;
  matrix_key: string;
  matrix_title: string;
  row_id: string;
  row_label: string;
  row_label_raw: string;
  row_type: string;
  column_label_raw: string;
  column_key: string | null;
  column_candidates: WordImportMatrixColumnCandidate[];
  raw_value: string;
  names: WordImportNameResolution[];
};

export type WordImportDuplicateProtocol = {
  id: number;
  protocol_number: string;
  title: string | null;
  protocol_date: string;
};

export type WordImportAnalysis = {
  protocol_date: string | null;
  tables: TablePreview[];
  text_mappings: WordImportTextMapping[];
  text_targets: WordImportTextTarget[];
  attendance_mappings: WordImportAttendanceMapping[];
  event_mappings: WordImportEventMapping[];
  list_definitions: WordImportListDefinitionOption[];
  list_mappings: WordImportListRowMapping[];
  matrix_options: WordImportMatrixOption[];
  matrix_mappings: WordImportMatrixCellMapping[];
  profile_applied: boolean;
  warnings: string[];
  duplicate_protocols: WordImportDuplicateProtocol[];
};

export type TableRoleOverride = {
  role: TableRole;
  list_definition_id: number | null;
  matrix_key?: string | null;
  // Only meaningful for role "list" - forces a specific grouping interpretation
  // instead of letting analyze() auto-score variants (see ListGroupingStrategy).
  // null/undefined lets the server pick automatically.
  list_grouping_strategy?: ListGroupingStrategy | null;
};

export type WordImportCommitPayload = {
  template_id: number;
  protocol_date: string;
  texts: {
    extracted_heading: string;
    content: string;
    template_element_id: number | null;
    block_sort_index: number | null;
    is_event_repeat: boolean;
    linked_event_id: number | null;
    is_form_block: boolean;
    form_fields: WordImportFormFieldValue[];
  }[];
  attendance: {
    raw_name: string;
    participant_id: number | null;
    participant_name: string;
    status: string;
    create_new: boolean;
    originally_suggested_participant_id: number | null;
    originally_suggested_score: number | null;
  }[];
  events: {
    approved: boolean;
    linked_event_id: number | null;
    final_title: string;
    final_date: string;
    raw_title: string;
    raw_date: string | null;
    tag: string | null;
    participant_count: number | null;
    originally_suggested_event_id: number | null;
    originally_suggested_score: number | null;
  }[];
  lists: {
    table_index: number;
    list_definition_id: number;
    column_one_raw: string;
    column_two_raw: string;
    column_one_names: WordImportNameResolution[];
    column_two_names: WordImportNameResolution[];
    approved: boolean;
    linked_entry_id: number | null;
    originally_suggested_entry_id: number | null;
    originally_suggested_score: number | null;
  }[];
  matrices: {
    matrix_key: string;
    row_id: string;
    row_type: string;
    column_key: string;
    column_label: string;
    raw_value: string;
    names: WordImportNameResolution[];
    approved: boolean;
    originally_suggested_column_key: string | null;
    originally_suggested_score: number | null;
  }[];
  tables: {
    header_signature: string;
    role: TableRole;
    list_definition_id: number | null;
    matrix_key: string | null;
    list_grouping_strategy: ListGroupingStrategy | null;
    originally_suggested_role: TableRole | null;
    originally_suggested_score: number | null;
  }[];
};

export async function analyzeWordImport(
  file: File,
  templateId: number,
  protocolDateHint: string | null,
  tableRoles?: Record<number, TableRoleOverride>
): Promise<WordImportAnalysis> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("template_id", String(templateId));
  if (protocolDateHint) formData.append("protocol_date_hint", protocolDateHint);
  if (tableRoles) formData.append("table_roles_json", JSON.stringify(tableRoles));
  return browserApiFetch<WordImportAnalysis>("/api/tools/word-import/analyze", { method: "POST", body: formData });
}

export type WordImportCommitResult = { id: number; warnings: string[] };

export async function commitWordImport(payload: WordImportCommitPayload): Promise<WordImportCommitResult> {
  return browserApiFetch<WordImportCommitResult>("/api/tools/word-import/commit", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export type WordImportDocumentStatus = "eingelesen" | "importiert";

export type WordImportDuplicateCandidate = {
  id: number;
  display_name: string;
  original_filename: string;
  status: WordImportDocumentStatus;
  protocol_id: number | null;
};

export type WordImportDocumentSummary = {
  id: number;
  template_id: number;
  template_name: string;
  display_name: string;
  original_filename: string;
  status: WordImportDocumentStatus;
  protocol_id: number | null;
  protocol_date: string | null;
  created_at: string;
  imported_at: string | null;
  stored_file_id: number;
  // Other queue documents (open or already imported) sharing the same recognized
  // protocol_date + template - likely the same protocol uploaded twice, e.g. once as
  // .docx and once as .pdf, or under a different filename.
  duplicates: WordImportDuplicateCandidate[];
};

// Opaque to the backend - shape is owned by the wizard (see WordImportReviewDraft there).
// Typed loosely here since lib/api is not where the review-draft shape should be defined.
export type WordImportReviewDraftJson = Record<string, unknown>;

export type WordImportDocumentDetail = WordImportDocumentSummary & {
  analysis: WordImportAnalysis;
  review_draft: WordImportReviewDraftJson;
};

export type WordImportDocumentUploadResult = {
  documents: WordImportDocumentSummary[];
  errors: string[];
};

// One batch = one template (see the queue's upload panel) - files are analyzed
// immediately server-side and land in the queue with status "eingelesen".
export async function ingestWordImportDocuments(templateId: number, files: File[]): Promise<WordImportDocumentUploadResult> {
  const formData = new FormData();
  formData.append("template_id", String(templateId));
  files.forEach((file) => formData.append("files", file));
  return browserApiFetch<WordImportDocumentUploadResult>("/api/tools/word-import/documents", { method: "POST", body: formData });
}

export async function listWordImportDocuments(status?: WordImportDocumentStatus): Promise<WordImportDocumentSummary[]> {
  const query = status ? `?status_filter=${status}` : "";
  return browserApiFetch<WordImportDocumentSummary[]>(`/api/tools/word-import/documents${query}`);
}

export async function getWordImportDocument(documentId: number): Promise<WordImportDocumentDetail> {
  return browserApiFetch<WordImportDocumentDetail>(`/api/tools/word-import/documents/${documentId}`);
}

export async function reanalyzeWordImportDocument(
  documentId: number,
  protocolDate: string | null,
  tableRoles: Record<number, TableRoleOverride>
): Promise<WordImportAnalysis> {
  return browserApiFetch<WordImportAnalysis>(`/api/tools/word-import/documents/${documentId}/reanalyze`, {
    method: "POST",
    body: JSON.stringify({ protocol_date: protocolDate, table_roles: tableRoles }),
  });
}

export async function commitWordImportDocument(documentId: number, payload: WordImportCommitPayload): Promise<WordImportCommitResult> {
  return browserApiFetch<WordImportCommitResult>(`/api/tools/word-import/documents/${documentId}/commit`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function saveWordImportDocumentDraft(documentId: number, draft: WordImportReviewDraftJson): Promise<void> {
  await browserApiFetch(`/api/tools/word-import/documents/${documentId}/draft`, {
    method: "PUT",
    body: JSON.stringify({ draft }),
  });
}

export async function deleteWordImportDocument(documentId: number): Promise<void> {
  await browserApiFetch(`/api/tools/word-import/documents/${documentId}`, { method: "DELETE" });
}
