import { browserApiFetch } from "@/lib/api/client";

export type TableRole = "attendance" | "events" | "list" | "ignore";
export type EventMatchStatus = "matched" | "changed" | "new";
export type ListRowStatus = "matched" | "changed" | "new";

export type TablePreview = {
  index: number;
  header_cells: string[];
  sample_rows: string[][];
  role: TableRole;
  list_definition_id: number | null;
  has_snapshot_target: boolean;
};

export type WordImportNameResolution = {
  raw_name: string;
  participant_id: number | null;
  create_new: boolean;
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

export type WordImportAttendanceMapping = {
  raw_name: string;
  status: string;
  suggested_participant_id: number | null;
  candidates: number[];
};

export type WordImportEventCandidate = {
  event_id: number;
  title: string;
  event_date: string;
  score: number;
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
  profile_applied: boolean;
  warnings: string[];
};

export type TableRoleOverride = { role: TableRole; list_definition_id: number | null };

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
  attendance: { raw_name: string; participant_id: number | null; participant_name: string; status: string; create_new: boolean }[];
  events: {
    approved: boolean;
    linked_event_id: number | null;
    final_title: string;
    final_date: string;
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
  }[];
  tables: { header_signature: string; role: TableRole; list_definition_id: number | null }[];
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

export async function commitWordImport(payload: WordImportCommitPayload): Promise<{ id: number }> {
  return browserApiFetch<{ id: number }>("/api/tools/word-import/commit", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export type WordImportDocumentStatus = "eingelesen" | "importiert";

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
};

export type WordImportDocumentDetail = WordImportDocumentSummary & {
  analysis: WordImportAnalysis;
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

export async function commitWordImportDocument(documentId: number, payload: WordImportCommitPayload): Promise<{ id: number }> {
  return browserApiFetch<{ id: number }>(`/api/tools/word-import/documents/${documentId}/commit`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function deleteWordImportDocument(documentId: number): Promise<void> {
  await browserApiFetch(`/api/tools/word-import/documents/${documentId}`, { method: "DELETE" });
}
