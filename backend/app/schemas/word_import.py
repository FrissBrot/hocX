from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

WordImportDocumentStatus = Literal["eingelesen", "importiert"]

TableRole = Literal["attendance", "events", "list", "matrix", "ignore"]
EventMatchStatus = Literal["matched", "changed", "new"]
ListRowStatus = Literal["matched", "changed", "new"]


class TablePreview(BaseModel):
    index: int
    header_cells: list[str] = Field(default_factory=list)
    sample_rows: list[list[str]] = Field(default_factory=list)
    role: TableRole = "ignore"
    list_definition_id: int | None = None
    # Only meaningful for role == "matrix": which template Matrix block this table was
    # matched against, see WordImportMatrixOption/matrix_options.
    matrix_key: str | None = None
    # Only meaningful for role == "list": whether the chosen template already has a
    # block linked to this list, i.e. whether there's a snapshot slot to import into
    # at all (lists are never written live - see WordImportListRowMapping docstring).
    has_snapshot_target: bool = True
    # Only meaningful for role == "list": which row-grouping interpretation of this
    # table's raw cells was used to build list_mappings (see
    # WordImportService._select_list_row_variant) - "flat"/"fill_down"/"swap", or an
    # exploded split keyed "explode:<delimiter>"/"explode_swap:<delimiter>" (delimiter
    # is one of _LIST_SPLIT_DELIMITERS, e.g. "explode_swap:comma"). None if this table
    # isn't a list at all.
    grouping_strategy: str | None = None
    # True when the target list has no live entries yet, so no automatic
    # variant-scoring was possible - the wizard must offer a manual strategy picker
    # for this table instead of trusting the "flat" default silently.
    needs_manual_grouping: bool = False
    # Every grouping_strategy value _build_list_row_variants actually produced for this
    # table's real data (delimiters that don't occur in the cells never appear here) -
    # lets the wizard's manual picker only ever offer choices that exist for real.
    available_grouping_strategies: list[str] = Field(default_factory=list)
    # True when `role` came from an explicit source (a manual override on this call, or
    # a learned profile signature match) rather than a keyword/heading-similarity guess -
    # mirrors _resolve_table_role's own 4th return value. Used by the import-queue's
    # batch consensus pass (WordImportQueueService) to decide which tables are confident
    # enough to vote on for sibling documents in the same upload batch.
    role_is_explicit: bool = False


class WordImportEventCandidate(BaseModel):
    event_id: int
    title: str
    event_date: date
    score: float = 0.0
    # Short human-readable justification (e.g. "Datum exakt, Titel 92% ähnlich") - see
    # word_import_service._event_match_reason. Empty string for candidates built before
    # this field existed (e.g. an old cached analysis_snapshot_json), never null.
    reason: str = ""


class WordImportAttendanceCandidate(BaseModel):
    """Shared candidate shape for any raw document name scored against the participant
    roster - used both by the attendance table (its own suggested_participant_id) and,
    via WordImportNameResolution.candidates below, by every other name-bearing mapping
    (lists/matrices/form fields), so the wizard's cross-document "wiederkehrende Namen"
    clarifier can rank a merged suggestion regardless of where the name occurred."""

    participant_id: int
    score: float = 0.0
    reason: str = ""


class WordImportNameResolution(BaseModel):
    raw_name: str
    participant_id: int | None = None
    # Only meaningful on commit, and only where the wizard actually offers a "create as
    # new participant" choice (currently just form-block name rows, mirroring the
    # attendance table's create_new) - participant_id=None + create_new=True means
    # "create a new Participant named raw_name instead of linking an existing one".
    create_new: bool = False
    # True when the reviewer explicitly resolved this name as "Keinen verknüpfen" (as
    # opposed to simply never having looked at it) - participant_id stays None either
    # way, so without this flag the wizard's recurring-name clarifier (see
    # buildRecurringNameGroups) can't tell "still needs a decision" apart from "reviewer
    # already decided there's no participant here", and would keep counting an explicit
    # no-link decision as still open forever (dead end: RECURRING_NAME_MIN_COUNT-heavy
    # tables review step gate never clears). Purely a frontend/review bookkeeping flag -
    # commit() only ever looks at participant_id, which already means "don't link" in
    # both cases.
    no_link: bool = False
    # What analyze() originally auto-resolved this raw_name to, set once when this
    # resolution is first built and never touched again by the frontend afterward (the
    # wizard's edit handlers only ever update `participant_id` via object-spread, which
    # preserves this field unchanged) - lets commit() tell "algorithm's own suggestion,
    # unreviewed or confirmed" apart from "human explicitly picked something else",
    # without needing a separate approve/reject UI. None if analyze() found no match at
    # all (nothing to compare against, see WordImportService._log_outcome).
    originally_suggested_participant_id: int | None = None
    originally_suggested_score: float | None = None
    # Ranked near-miss alternatives (best first) even when nothing cleared the auto-link
    # threshold - lets the wizard's recurring-name clarifier suggest a participant for a
    # name that recurs across many rows without ever having auto-resolved anywhere.
    candidates: list[WordImportAttendanceCandidate] = Field(default_factory=list)


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
    # Set when the resolved target block has a `sync_target_field` configured (see
    # block_field_sync.SYNC_TARGET_FIELDS) - the block's content also gets written into this
    # column of the linked Event once matched_event_id is known. Only ever set alongside
    # is_event_repeat=True - "Pro Todo" blocks aren't import targets at all (see
    # event_repeat_block_keys in analyze(), todo-repeat blocks are skipped there because
    # there's no candidate mechanism to resolve a section to a specific Todo instance).
    sync_target_field: str | None = None
    # "empty": Event field has no value yet, written without asking. "match": Event field
    # already equals the extracted text, nothing to resolve. "conflict": Event field holds a
    # different existing value - the wizard must ask which one wins (see
    # WordImportTextCommit.sync_field_source, default "existing").
    sync_field_status: Literal["empty", "match", "conflict"] | None = None
    sync_field_existing_value: str | None = None


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
    candidates: list[WordImportAttendanceCandidate] = Field(default_factory=list)
    # Set when suggested_participant_id is None AND this exact raw name was already
    # explicitly resolved as "Keinen verknüpfen" (not a real participant - e.g. a
    # table's own "Total" footer row) in an earlier commit (see WordImportService.commit's
    # no_link_name_updates). Lets the wizard pre-apply that same decision instead of
    # re-flagging an already-resolved non-participant row every import.
    remembered_no_link: bool = False


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
    # Only set for rows extracted from a Matrix "events" row (a Matrix column's dates are
    # never stored per-cell - they're always resolved live at render time by matching an
    # Event's own `tag` against the column, see WordImportService.analyze) - the tag this
    # Event needs so it actually shows up in that Matrix column. None for ordinary
    # "events"-role table rows, whose tag is never touched by the importer.
    tag: str | None = None
    # Only set for rows extracted from a Matrix "events" row when a trailing "(N)" was
    # found right after the date (e.g. "18.10.2025 (7)") - the exact format
    # export_service._matrix_event_row_value writes for event_show_participant_count,
    # so a previously exported/re-imported protocol round-trips its attendance counts.
    participant_count: int | None = None
    # Matrix/row/column context, only set alongside `tag` (Matrix-sourced rows) - lets
    # the wizard group these back into the Matrix's own card layout instead of only
    # showing them in the flat Termine list.
    matrix_key: str | None = None
    matrix_title: str | None = None
    row_id: str | None = None
    row_label: str | None = None
    column_key: str | None = None
    column_label: str | None = None
    # Set when status == "changed" (raw_title/raw_date conflicts with an existing
    # matched Event) AND this same (event, raw_title) pair already got a resolution
    # decision in an earlier commit (see WordImportService._event_conflict_key / commit's
    # event_conflict_updates - deliberately NOT keyed on raw_date, so a yearly-recurring
    # Termin whose document mention always names a different/stale date still reuses the
    # same decision). Lets the wizard pre-apply that same decision and skip asking the
    # reviewer to reconfirm an already-resolved recurring conflict.
    remembered_title_source: Literal["doc", "existing"] | None = None
    remembered_date_source: Literal["doc", "existing"] | None = None


class WordImportListDefinitionOption(BaseModel):
    id: int
    name: str


class WordImportListEntryCandidate(BaseModel):
    entry_id: int
    column_one_display: str
    column_two_display: str
    score: float = 0.0
    reason: str = ""


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
    # True when this row's column_one_raw/column_two_raw grouping value was inferred
    # (fill-down from a previous row, or repeated across an exploded multi-value cell)
    # rather than literally present in this row's own document cell - see
    # ListRowCandidate.group_filled. Lets the wizard flag these rows for review.
    group_filled: bool = False


class WordImportMatrixOption(BaseModel):
    """One Matrix block target available in the chosen template - matrix_key encodes
    (template_element_id, block_sort_index), the same identity block_by_key already
    uses in WordImportService.commit, so a resolved match needs no separate lookup
    scheme."""

    matrix_key: str
    title: str


class WordImportMatrixColumnCandidate(BaseModel):
    column_key: str
    label: str
    score: float = 0.0
    reason: str = ""


class WordImportMatrixCellMapping(BaseModel):
    """One document row x column cell resolved against a fixed Matrix row and a
    (possibly not-yet-existing) Matrix column. Matrix rows are structurally fixed by
    the template - a document row that matches no configured row is dropped with a
    warning in analyze() instead of appearing here at all (unlike list rows, there's
    no "new row" concept). Columns can be brand new: participant/event/list
    auto-source columns are created on demand in commit() rather than needing to
    already exist - column_key is None when no column matched confidently enough,
    in which case the wizard offers column_candidates for a manual pick."""

    table_index: int
    matrix_key: str
    matrix_title: str
    row_id: str
    row_label: str
    row_label_raw: str
    row_type: str
    column_label_raw: str
    column_key: str | None = None
    column_candidates: list[WordImportMatrixColumnCandidate] = Field(default_factory=list)
    raw_value: str
    names: list[WordImportNameResolution] = Field(default_factory=list)


class WordImportDuplicateProtocol(BaseModel):
    """An existing Protocol (of any origin - manually created, or from an earlier
    import, standalone or via the queue) already using this template+date - see
    WordImportService.analyze's duplicate_protocols. Real bug fixed here: the queue's
    own duplicate hint (WordImportDuplicateCandidate) only ever compares against other
    WordImportDocument rows, so the standalone wizard (/tools/word-import, which never
    creates a WordImportDocument at all) was completely blind to an already-existing
    Protocol for the same date - this checks the Protocol table directly instead, so it
    catches a duplicate regardless of how the original was created."""

    id: int
    protocol_number: str
    title: str | None = None
    protocol_date: date


class WordImportAnalysis(BaseModel):
    protocol_date: date | None = None
    tables: list[TablePreview] = Field(default_factory=list)
    text_mappings: list[WordImportTextMapping] = Field(default_factory=list)
    text_targets: list[WordImportTextTarget] = Field(default_factory=list)
    attendance_mappings: list[WordImportAttendanceMapping] = Field(default_factory=list)
    event_mappings: list[WordImportEventMapping] = Field(default_factory=list)
    list_definitions: list[WordImportListDefinitionOption] = Field(default_factory=list)
    list_mappings: list[WordImportListRowMapping] = Field(default_factory=list)
    matrix_options: list[WordImportMatrixOption] = Field(default_factory=list)
    matrix_mappings: list[WordImportMatrixCellMapping] = Field(default_factory=list)
    profile_applied: bool = False
    warnings: list[str] = Field(default_factory=list)
    duplicate_protocols: list[WordImportDuplicateProtocol] = Field(default_factory=list)


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
    # Mirrors TextDraft.dismissed in the wizard ("Ignorieren" on a section without a
    # resolved template target, or a form block with an unresolved name) - skips writing
    # this section's block entirely, same row-level "Ignorieren" granularity the list/
    # matrix/event commit rows already have via their own `approved` flag.
    dismissed: bool = False
    # Reviewer's pick for WordImportTextMapping.sync_field_status == "conflict" - "doc" keeps
    # the extracted text (written into both the block and the Event field), "existing" keeps
    # the Event's current field value (written into both instead, so block and Event field
    # stay identical post-commit). None/unset when there was no conflict to resolve - commit()
    # then just writes `content` through as usual.
    sync_field_source: Literal["doc", "existing"] | None = None


class WordImportAttendanceCommit(BaseModel):
    raw_name: str
    # None + create_new=True means "no existing participant matched - create one
    # named participant_name instead of linking to an existing record".
    participant_id: int | None = None
    participant_name: str
    status: str
    create_new: bool = False
    # See WordImportNameResolution.originally_suggested_participant_id - same purpose,
    # populated once from WordImportAttendanceMapping.suggested_participant_id when the
    # wizard applies a fresh analysis, never updated afterward.
    originally_suggested_participant_id: int | None = None
    originally_suggested_score: float | None = None


class WordImportEventCommit(BaseModel):
    approved: bool
    # User's dropdown choice in the wizard: None = "Neu anlegen", otherwise the live
    # Event this row is linked to (created via create_event or updated via
    # update_event with the already per-field-resolved final_title/final_date below).
    linked_event_id: int | None = None
    final_title: str
    final_date: date
    # The document's own raw title/date, BEFORE the doc-vs-existing decision (see
    # final_title/final_date above) - not used to write the Event, only to key a
    # remembered resolution for this exact conflict (see WordImportService.commit /
    # _event_conflict_key) so an identical recurring conflict auto-resolves next time.
    raw_title: str
    raw_date: date | None = None
    # Mirrors WordImportEventMapping.tag - when set (Matrix-sourced row), the created/
    # updated Event's tag is set to this value so it appears in the right Matrix column.
    # None for ordinary Termine-table rows, whose tag is left untouched.
    tag: str | None = None
    # Mirrors WordImportEventMapping.participant_count - when set, the created/updated
    # Event's participant_count is set to this value. None leaves it untouched.
    participant_count: int | None = None
    # See WordImportNameResolution.originally_suggested_participant_id - same purpose,
    # populated once from WordImportEventMapping.matched_event_id (and its top
    # candidate's score) when the wizard applies a fresh analysis.
    originally_suggested_event_id: int | None = None
    originally_suggested_score: float | None = None


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
    # See WordImportNameResolution.originally_suggested_participant_id - same purpose,
    # populated once from WordImportListRowMapping.matched_entry_id.
    originally_suggested_entry_id: int | None = None
    originally_suggested_score: float | None = None


class WordImportMatrixCellCommit(BaseModel):
    """Unlike lists, matrix cells are written straight into the live protocol's own
    Matrix block (see WordImportService.commit) - there is no separate persisted
    entity to preserve a reference to, so this carries the resolved value itself."""

    matrix_key: str
    row_id: str
    row_type: str
    column_key: str
    column_label: str
    raw_value: str
    names: list[WordImportNameResolution] = Field(default_factory=list)
    approved: bool
    # See WordImportNameResolution.originally_suggested_participant_id - same purpose,
    # populated once from the matched column_key of WordImportMatrixCellMapping.
    originally_suggested_column_key: str | None = None
    originally_suggested_score: float | None = None


class WordImportTableRoleCommit(BaseModel):
    header_signature: str
    role: TableRole
    list_definition_id: int | None = None
    matrix_key: str | None = None
    # Mirrors TablePreview.grouping_strategy - remembered per table signature so a
    # recurring document layout (e.g. a monthly protocol) doesn't need the grouping
    # strategy re-picked on every import, same learning mechanism as role/
    # list_definition_id/matrix_key above.
    list_grouping_strategy: str | None = None
    # See WordImportNameResolution.originally_suggested_participant_id - same purpose,
    # populated once from the matching TablePreview.role when the wizard applies a
    # fresh analysis (score is 1.0 when TablePreview.role_is_explicit, else omitted).
    originally_suggested_role: TableRole | None = None
    originally_suggested_score: float | None = None


class WordImportCommit(BaseModel):
    template_id: int
    protocol_date: date
    texts: list[WordImportTextCommit] = Field(default_factory=list)
    attendance: list[WordImportAttendanceCommit] = Field(default_factory=list)
    events: list[WordImportEventCommit] = Field(default_factory=list)
    lists: list[WordImportListRowCommit] = Field(default_factory=list)
    matrices: list[WordImportMatrixCellCommit] = Field(default_factory=list)
    tables: list[WordImportTableRoleCommit] = Field(default_factory=list)


class WordImportCommitResult(BaseModel):
    """Previously commit() returned just the new Protocol's id - several failure modes
    inside it (an unresolvable event-repeat/matrix block, a malformed matrix_key, two
    document sections resolving to the same block, a resolved block missing its
    ProtocolText row) were silently swallowed with a bare `continue`, so content could
    go missing with zero indication to the reviewer. `warnings` surfaces those same
    skips instead of only ever being empty."""

    id: int
    warnings: list[str] = Field(default_factory=list)


class WordImportDuplicateCandidate(BaseModel):
    """Another queue document (open or already imported) sharing the same recognized
    protocol_date + template as the document this is attached to - surfaced so the user
    can decide whether it's genuinely the same protocol uploaded twice (in another
    format or under another filename) or a coincidental same-day duplicate."""

    id: int
    display_name: str
    original_filename: str
    status: WordImportDocumentStatus
    protocol_id: int | None = None

    model_config = {"from_attributes": True}


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
    duplicates: list[WordImportDuplicateCandidate] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class WordImportDocumentDetail(WordImportDocumentSummary):
    analysis: WordImportAnalysis
    # Opaque reviewer draft (see WordImportDocument.review_draft_json) - {} if none saved
    # yet or if it was reset by a reanalyze since it was last saved.
    review_draft: dict[str, Any] = Field(default_factory=dict)


class WordImportDraftSave(BaseModel):
    draft: dict[str, Any] = Field(default_factory=dict)


class WordImportDocumentUploadResult(BaseModel):
    documents: list[WordImportDocumentSummary] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class WordImportDocumentReanalyzeRequest(BaseModel):
    protocol_date: date | None = None
    table_roles: dict[int, dict] = Field(default_factory=dict)


class WordImportQualityBucket(BaseModel):
    """Accept-rate of one signal_type's suggestions within one 0.1-wide score band
    (e.g. signal_type="event_match", score_bucket=0.8 covers suggested_score in
    [0.8, 0.9)) - see WordImportQualityService.accept_rate_stats."""

    signal_type: str
    score_bucket: float
    sample_count: int
    accept_rate: float


class WordImportQualityStats(BaseModel):
    buckets: list[WordImportQualityBucket] = Field(default_factory=list)
