from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

WordImportDocumentStatus = Literal["eingelesen", "importiert"]

TableRole = Literal["attendance", "events", "list", "ignore"]
EventMatchStatus = Literal["matched", "changed", "new"]
ListRowStatus = Literal["matched", "changed", "new"]


class TablePreview(BaseModel):
    index: int
    header_cells: list[str] = Field(default_factory=list)
    sample_rows: list[list[str]] = Field(default_factory=list)
    role: TableRole = "ignore"
    list_definition_id: int | None = None
    # Only meaningful for role == "list": whether the chosen template already has a
    # block linked to this list, i.e. whether there's a snapshot slot to import into
    # at all (lists are never written live - see WordImportListRowMapping docstring).
    has_snapshot_target: bool = True


class WordImportEventCandidate(BaseModel):
    event_id: int
    title: str
    event_date: date
    score: float = 0.0


class WordImportNameResolution(BaseModel):
    raw_name: str
    participant_id: int | None = None
    # Only meaningful on commit, and only where the wizard actually offers a "create as
    # new participant" choice (currently just form-block name rows, mirroring the
    # attendance table's create_new) - participant_id=None + create_new=True means
    # "create a new Participant named raw_name instead of linking an existing one".
    create_new: bool = False


class WordImportFormRow(BaseModel):
    """One configured row of a "form" block target (e.g. "Organisation"/"Wer geht" on a
    Scharanlässe-style block) - describes the row's shape, doesn't carry a value."""

    row_id: str
    label: str
    row_type: str


class WordImportFormFieldValue(BaseModel):
    """One row's extracted (mapping) or user-edited (commit) value for a form-block text
    target. raw_value holds the plain text for row_type "text", or the still-unresolved
    name text for "participant"/"participants" (see names for the resolved id(s), same
    raw_name/participant_id convention as elsewhere). Rows of type "event"/"list_entry"
    are recognized but never populated/written - out of scope for this import path."""

    row_id: str
    label: str
    row_type: str
    raw_value: str = ""
    names: list[WordImportNameResolution] = Field(default_factory=list)


class WordImportTextMapping(BaseModel):
    extracted_heading: str
    extracted_text: str
    template_element_id: int | None = None
    block_sort_index: int | None = None
    confidence: float = 0.0
    # True when the resolved target block has repeat_source == "event" (e.g. a
    # "Rückblick"/review block, one instance per linked Event - see
    # ProtocolService.add_event_block_to_element). Such a block exists once per Event,
    # so (template_element_id, block_sort_index) alone can't identify the right
    # instance - it must additionally be resolved to a specific Event via
    # matched_event_id/event_candidates.
    is_event_repeat: bool = False
    matched_event_id: int | None = None
    event_candidates: list[WordImportEventCandidate] = Field(default_factory=list)
    # True when the resolved target is a "form" block (fixed labeled rows, e.g.
    # Organisation/Wer geht/Treffpunkt) rather than free text - form_fields then holds one
    # entry per configured row, extracted from "Label: Value" lines in extracted_text (see
    # word_import_service._parse_form_fields) instead of extracted_text being used
    # directly as a block's content.
    is_form_block: bool = False
    form_fields: list[WordImportFormFieldValue] = Field(default_factory=list)
    # form_fields parsed against EVERY form-block target in the template (keyed by
    # "{template_element_id}:{block_sort_index}", same format as the frontend's
    # targetKey()), not just the currently matched one - mirrors why event_candidates is
    # computed unconditionally above. Without this, manually switching a section's target
    # to a form block that wasn't the auto-match (e.g. the initial match failed and
    # template_element_id was None) would have no parsed values to show and silently
    # fall back to blank fields, exactly like the event_candidates bug fixed earlier.
    form_fields_by_target: dict[str, list[WordImportFormFieldValue]] = Field(default_factory=dict)


class WordImportTextTarget(BaseModel):
    template_element_id: int
    block_sort_index: int
    label: str
    is_event_repeat: bool = False
    is_form_block: bool = False
    form_rows: list[WordImportFormRow] = Field(default_factory=list)


class WordImportAttendanceMapping(BaseModel):
    raw_name: str
    status: str = "present"
    suggested_participant_id: int | None = None
    candidates: list[int] = Field(default_factory=list)


class WordImportEventMapping(BaseModel):
    row_index: int
    raw_title: str
    raw_date: date | None = None
    status: EventMatchStatus
    matched_event_id: int | None = None
    matched_event_title: str | None = None
    matched_event_date: date | None = None
    # Ranked alternatives (best first, top match included) so the wizard can offer a
    # dropdown instead of only the single auto-picked candidate.
    candidates: list[WordImportEventCandidate] = Field(default_factory=list)


class WordImportListDefinitionOption(BaseModel):
    id: int
    name: str


class WordImportListEntryCandidate(BaseModel):
    entry_id: int
    column_one_display: str
    column_two_display: str
    score: float = 0.0


class WordImportListRowMapping(BaseModel):
    """List rows are never written to the live ListEntry table on commit (see
    WordImportService.commit) - an old document may mention an entry ("Amt X: Hans")
    that no longer holds today, and reviving it live would make stale data look
    current. Instead matched/changed/new rows all land only in the snapshot of the
    list-linked block the chosen template already has (see has_snapshot_target)."""

    table_index: int
    row_index: int
    column_one_raw: str
    column_two_raw: str
    column_one_type: str
    column_two_type: str
    status: ListRowStatus
    matched_entry_id: int | None = None
    column_one_names: list[WordImportNameResolution] = Field(default_factory=list)
    column_two_names: list[WordImportNameResolution] = Field(default_factory=list)
    candidates: list[WordImportListEntryCandidate] = Field(default_factory=list)
    has_snapshot_target: bool = True


class WordImportAnalysis(BaseModel):
    protocol_date: date | None = None
    tables: list[TablePreview] = Field(default_factory=list)
    text_mappings: list[WordImportTextMapping] = Field(default_factory=list)
    text_targets: list[WordImportTextTarget] = Field(default_factory=list)
    attendance_mappings: list[WordImportAttendanceMapping] = Field(default_factory=list)
    event_mappings: list[WordImportEventMapping] = Field(default_factory=list)
    list_definitions: list[WordImportListDefinitionOption] = Field(default_factory=list)
    list_mappings: list[WordImportListRowMapping] = Field(default_factory=list)
    profile_applied: bool = False
    warnings: list[str] = Field(default_factory=list)


class WordImportTextCommit(BaseModel):
    extracted_heading: str
    content: str
    template_element_id: int | None = None
    block_sort_index: int | None = None
    # Mirrors WordImportTextMapping.is_event_repeat/matched_event_id - when true,
    # block_sort_index alone can't identify the right block (one exists per Event), so
    # commit() resolves/creates the block for linked_event_id instead. A row with
    # is_event_repeat=True and linked_event_id=None is skipped entirely (never falls
    # back to block_sort_index, which would write into an arbitrary other Event's block).
    is_event_repeat: bool = False
    linked_event_id: int | None = None
    # Mirrors WordImportTextMapping.is_form_block/form_fields - when true, content is
    # ignored and each form_fields[i] is written into the matching row (by row_id) of the
    # target block's configuration_snapshot_json["rows"] instead of a ProtocolText.
    is_form_block: bool = False
    form_fields: list[WordImportFormFieldValue] = Field(default_factory=list)


class WordImportAttendanceCommit(BaseModel):
    raw_name: str
    # None + create_new=True means "no existing participant matched - create one
    # named participant_name instead of linking to an existing record".
    participant_id: int | None = None
    participant_name: str
    status: str
    create_new: bool = False


class WordImportEventCommit(BaseModel):
    approved: bool
    # User's dropdown choice in the wizard: None = "Neu anlegen", otherwise the live
    # Event this row is linked to (created via create_event or updated via
    # update_event with the already per-field-resolved final_title/final_date below).
    linked_event_id: int | None = None
    final_title: str
    final_date: date


class WordImportListRowCommit(BaseModel):
    """Lists are always written into the protocol's own block snapshot, never live -
    see WordImportListRowMapping. linked_entry_id (if set) is only used to preserve
    the live-reference id inside that snapshot row/entry, it is never written to."""

    table_index: int
    list_definition_id: int
    column_one_raw: str
    column_two_raw: str
    column_one_names: list[WordImportNameResolution] = Field(default_factory=list)
    column_two_names: list[WordImportNameResolution] = Field(default_factory=list)
    approved: bool
    linked_entry_id: int | None = None


class WordImportTableRoleCommit(BaseModel):
    header_signature: str
    role: TableRole
    list_definition_id: int | None = None


class WordImportCommit(BaseModel):
    template_id: int
    protocol_date: date
    texts: list[WordImportTextCommit] = Field(default_factory=list)
    attendance: list[WordImportAttendanceCommit] = Field(default_factory=list)
    events: list[WordImportEventCommit] = Field(default_factory=list)
    lists: list[WordImportListRowCommit] = Field(default_factory=list)
    tables: list[WordImportTableRoleCommit] = Field(default_factory=list)


class WordImportDocumentSummary(BaseModel):
    """One row of the multi-document import queue (`/tools/import`) - a stored upload
    that has either only been read in ('eingelesen') or already turned into a protocol
    ('importiert', in which case protocol_id/imported_at/imported_by are set)."""

    id: int
    template_id: int
    template_name: str
    display_name: str
    original_filename: str
    status: WordImportDocumentStatus
    protocol_id: int | None = None
    protocol_date: date | None = None
    created_at: datetime
    imported_at: datetime | None = None
    stored_file_id: int

    model_config = {"from_attributes": True}


class WordImportDocumentDetail(WordImportDocumentSummary):
    analysis: WordImportAnalysis


class WordImportDocumentUploadResult(BaseModel):
    documents: list[WordImportDocumentSummary] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class WordImportDocumentReanalyzeRequest(BaseModel):
    protocol_date: date | None = None
    table_roles: dict[int, dict] = Field(default_factory=dict)
