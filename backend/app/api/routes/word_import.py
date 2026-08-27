import json
import uuid
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, require_writer
from app.models import (
    Event,
    ListDefinition,
    ListEntry,
    Participant,
    Protocol,
    StoredFile,
    Template,
    TemplateElement,
    Tenant,
    WordImportDocument,
)
from app.schemas.word_import import (
    PublicTablePreview,
    PublicWordImportAnalysis,
    PublicWordImportAttendanceCandidate,
    PublicWordImportAttendanceMapping,
    PublicWordImportCommit,
    PublicWordImportCommitResult,
    PublicWordImportDocumentDetail,
    PublicWordImportDocumentSummary,
    PublicWordImportDocumentUploadResult,
    PublicWordImportDuplicateCandidate,
    PublicWordImportDuplicateProtocol,
    PublicWordImportEventCandidate,
    PublicWordImportEventMapping,
    PublicWordImportFormFieldValue,
    PublicWordImportLastTemplate,
    PublicWordImportListDefinitionOption,
    PublicWordImportListEntryCandidate,
    PublicWordImportListRowMapping,
    PublicWordImportMatrixCellMapping,
    PublicWordImportNameResolution,
    PublicWordImportTextMapping,
    PublicWordImportTextTarget,
    WordImportAnalysis,
    WordImportAttendanceCandidate,
    WordImportAttendanceCommit,
    WordImportCommit,
    WordImportCommitResult,
    WordImportDocumentDetail,
    WordImportDocumentReanalyzeRequest,
    WordImportDocumentSummary,
    WordImportDraftSave,
    WordImportDuplicateCandidate,
    WordImportEventCandidate,
    WordImportEventCommit,
    WordImportFormFieldValue,
    WordImportListRowCommit,
    WordImportMatrixCellCommit,
    WordImportNameResolution,
    WordImportQualityBucket,
    WordImportQualityStats,
    WordImportTableRoleCommit,
    WordImportTextCommit,
)
from app.services import public_id_service
from app.services.file_service import MAX_UPLOAD_BYTES, MAX_ZIP_TOTAL_BYTES, extract_word_import_files_from_zip
from app.services.word_import_quality_service import WordImportQualityService
from app.services.word_import_queue_service import WordImportQueueService
from app.services.word_import_service import WordImportService

router = APIRouter()
service = WordImportService()
queue_service = WordImportQueueService()
quality_service = WordImportQualityService()

# Ganzer Batch (Summe aller akzeptierten Dateien eines Upload-Requests, ausserhalb von
# ZIPs - deren eigener Grenzwert ist MAX_ZIP_TOTAL_BYTES): grösszügiger als eine einzelne
# Datei, aber trotzdem endlich, damit ein Request mit vielen knapp-unter-dem-Limit-Dateien
# nicht beliebig viel RAM/Platte/Parse-Zeit binden kann.
MAX_WORD_IMPORT_BATCH_FILES = 50
MAX_WORD_IMPORT_BATCH_BYTES = 150 * 1024 * 1024


async def _read_upload_within_limit(file: UploadFile, max_bytes: int) -> bytes | None:
    """Rejects an oversized upload using Starlette's already-known `.size` (populated by
    the multipart parser before the route runs, see UploadFile.write) instead of buffering
    the whole thing into a `bytes` object first just to measure it - a file that's already
    over the limit never gets fully materialized in memory this way. Returns None if too
    large."""
    if file.size is not None and file.size > max_bytes:
        return None
    content = await file.read()
    if len(content) > max_bytes:
        return None
    return content


def _resolve_template_id(db: Session, tenant_id: int, template_id: uuid.UUID) -> int:
    internal_id = public_id_service.resolve_internal_id(db, Template, template_id, tenant_id=tenant_id)
    if internal_id is None:
        raise HTTPException(status_code=400, detail="Vorlage nicht gefunden")
    return internal_id


def _resolve_document_id(db: Session, tenant_id: int, document_id: uuid.UUID) -> int:
    internal_id = public_id_service.resolve_internal_id(db, WordImportDocument, document_id, tenant_id=tenant_id)
    if internal_id is None:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    return internal_id


# ---------------------------------------------------------------------------
# TemplateElement and ListEntry have no tenant_id column of their own (they're
# only transitively tenant-scoped, via template_id -> Template.tenant_id resp.
# list_definition_id -> ListDefinition.tenant_id) - see public_id_service's
# module docstring. Passing tenant_id= straight into resolve_internal_id(s) for
# these two models would silently no-op (public_id_service only filters by
# tenant_id when the model has that column), which would let a client
# reference another tenant's TemplateElement/ListEntry by guessing its public
# id. These two helpers do the join-based tenant scoping ourselves instead.
# ---------------------------------------------------------------------------


def _resolve_template_element_ids(
    db: Session, tenant_id: int, public_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    unique_ids = {i for i in public_ids if i is not None}
    if not unique_ids:
        return {}
    statement = (
        select(TemplateElement.public_id, TemplateElement.id)
        .join(Template, Template.id == TemplateElement.template_id)
        .where(TemplateElement.public_id.in_(unique_ids), Template.tenant_id == tenant_id)
    )
    return dict(db.execute(statement).all())


def _resolve_list_entry_ids(db: Session, tenant_id: int, public_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    unique_ids = {i for i in public_ids if i is not None}
    if not unique_ids:
        return {}
    statement = (
        select(ListEntry.public_id, ListEntry.id)
        .join(ListDefinition, ListDefinition.id == ListEntry.list_definition_id)
        .where(ListEntry.public_id.in_(unique_ids), ListDefinition.tenant_id == tenant_id)
    )
    return dict(db.execute(statement).all())


# ---------------------------------------------------------------------------
# Encode direction: internal (int-id) WordImport* -> Public (uuid-id) mirror.
# Used for every HTTP response. Implemented as a collect-then-batch-resolve-
# then-rewrite pass over the whole WordImportAnalysis tree, to avoid N+1
# queries (event/attendance/list mappings can each be dozens+ rows).
# ---------------------------------------------------------------------------


def _pub(id_map: dict[int, uuid.UUID], internal_id: int | None, what: str) -> uuid.UUID | None:
    if internal_id is None:
        return None
    try:
        return id_map[internal_id]
    except KeyError:
        # Defensive only - these internal ids came from queries the service already
        # tenant-scoped, so a miss here means resolve_public_ids was never called for
        # this model/id, not a real "not found". Never silently emit a wrong/null id.
        raise RuntimeError(f"public_id_service: no public_id resolved for {what} id={internal_id}") from None


def _collect_analysis_ids(
    analysis: WordImportAnalysis,
) -> tuple[set[int], set[int], set[int], set[int], set[int], set[int]]:
    list_definition_ids: set[int] = set()
    event_ids: set[int] = set()
    participant_ids: set[int] = set()
    template_element_ids: set[int] = set()
    list_entry_ids: set[int] = set()
    protocol_ids: set[int] = set()

    def collect_name(name: WordImportNameResolution) -> None:
        if name.participant_id is not None:
            participant_ids.add(name.participant_id)
        if name.originally_suggested_participant_id is not None:
            participant_ids.add(name.originally_suggested_participant_id)
        for candidate in name.candidates:
            participant_ids.add(candidate.participant_id)

    def collect_form_field(field: WordImportFormFieldValue) -> None:
        for name in field.names:
            collect_name(name)

    for table in analysis.tables:
        if table.list_definition_id is not None:
            list_definition_ids.add(table.list_definition_id)

    for text_mapping in analysis.text_mappings:
        if text_mapping.template_element_id is not None:
            template_element_ids.add(text_mapping.template_element_id)
        if text_mapping.matched_event_id is not None:
            event_ids.add(text_mapping.matched_event_id)
        for candidate in text_mapping.event_candidates:
            event_ids.add(candidate.event_id)
        for field in text_mapping.form_fields:
            collect_form_field(field)
        for fields in text_mapping.form_fields_by_target.values():
            for field in fields:
                collect_form_field(field)

    for target in analysis.text_targets:
        template_element_ids.add(target.template_element_id)

    for attendance_mapping in analysis.attendance_mappings:
        if attendance_mapping.suggested_participant_id is not None:
            participant_ids.add(attendance_mapping.suggested_participant_id)
        for candidate in attendance_mapping.candidates:
            participant_ids.add(candidate.participant_id)

    for event_mapping in analysis.event_mappings:
        if event_mapping.matched_event_id is not None:
            event_ids.add(event_mapping.matched_event_id)
        for candidate in event_mapping.candidates:
            event_ids.add(candidate.event_id)

    for list_definition in analysis.list_definitions:
        list_definition_ids.add(list_definition.id)

    for list_mapping in analysis.list_mappings:
        if list_mapping.matched_entry_id is not None:
            list_entry_ids.add(list_mapping.matched_entry_id)
        for name in list_mapping.column_one_names:
            collect_name(name)
        for name in list_mapping.column_two_names:
            collect_name(name)
        for candidate in list_mapping.candidates:
            list_entry_ids.add(candidate.entry_id)

    for matrix_mapping in analysis.matrix_mappings:
        for name in matrix_mapping.names:
            collect_name(name)

    for duplicate_protocol in analysis.duplicate_protocols:
        protocol_ids.add(duplicate_protocol.id)

    return list_definition_ids, event_ids, participant_ids, template_element_ids, list_entry_ids, protocol_ids


def _encode_attendance_candidate(
    candidate: WordImportAttendanceCandidate, participants: dict[int, uuid.UUID]
) -> PublicWordImportAttendanceCandidate:
    return PublicWordImportAttendanceCandidate(
        participant_id=_pub(participants, candidate.participant_id, "participant"),
        score=candidate.score,
        reason=candidate.reason,
    )


def _encode_event_candidate(
    candidate: WordImportEventCandidate, events: dict[int, uuid.UUID]
) -> PublicWordImportEventCandidate:
    return PublicWordImportEventCandidate(
        event_id=_pub(events, candidate.event_id, "event"),
        title=candidate.title,
        event_date=candidate.event_date,
        event_end_date=candidate.event_end_date,
        score=candidate.score,
        reason=candidate.reason,
    )


def _encode_name_resolution(
    name: WordImportNameResolution, participants: dict[int, uuid.UUID]
) -> PublicWordImportNameResolution:
    return PublicWordImportNameResolution(
        raw_name=name.raw_name,
        participant_id=_pub(participants, name.participant_id, "participant"),
        create_new=name.create_new,
        no_link=name.no_link,
        originally_suggested_participant_id=_pub(
            participants, name.originally_suggested_participant_id, "participant"
        ),
        originally_suggested_score=name.originally_suggested_score,
        candidates=[_encode_attendance_candidate(c, participants) for c in name.candidates],
    )


def _encode_form_field(
    field: WordImportFormFieldValue, participants: dict[int, uuid.UUID]
) -> PublicWordImportFormFieldValue:
    return PublicWordImportFormFieldValue(
        row_id=field.row_id,
        label=field.label,
        row_type=field.row_type,
        raw_value=field.raw_value,
        names=[_encode_name_resolution(n, participants) for n in field.names],
    )


def _encode_analysis(db: Session, analysis: WordImportAnalysis) -> PublicWordImportAnalysis:
    list_definition_ids, event_ids, participant_ids, template_element_ids, list_entry_ids, protocol_ids = (
        _collect_analysis_ids(analysis)
    )

    list_definitions = public_id_service.resolve_public_ids(db, ListDefinition, list(list_definition_ids))
    events = public_id_service.resolve_public_ids(db, Event, list(event_ids))
    participants = public_id_service.resolve_public_ids(db, Participant, list(participant_ids))
    template_elements = public_id_service.resolve_public_ids(db, TemplateElement, list(template_element_ids))
    list_entries = public_id_service.resolve_public_ids(db, ListEntry, list(list_entry_ids))
    protocols = public_id_service.resolve_public_ids(db, Protocol, list(protocol_ids))

    tables = [
        PublicTablePreview(
            index=t.index,
            header_cells=t.header_cells,
            sample_rows=t.sample_rows,
            role=t.role,
            list_definition_id=_pub(list_definitions, t.list_definition_id, "list_definition"),
            matrix_key=t.matrix_key,
            has_snapshot_target=t.has_snapshot_target,
            grouping_strategy=t.grouping_strategy,
            needs_manual_grouping=t.needs_manual_grouping,
            available_grouping_strategies=t.available_grouping_strategies,
            role_is_explicit=t.role_is_explicit,
        )
        for t in analysis.tables
    ]

    text_mappings = [
        PublicWordImportTextMapping(
            extracted_heading=tm.extracted_heading,
            extracted_text=tm.extracted_text,
            template_element_id=_pub(template_elements, tm.template_element_id, "template_element"),
            block_sort_index=tm.block_sort_index,
            confidence=tm.confidence,
            is_event_repeat=tm.is_event_repeat,
            matched_event_id=_pub(events, tm.matched_event_id, "event"),
            event_candidates=[_encode_event_candidate(c, events) for c in tm.event_candidates],
            is_form_block=tm.is_form_block,
            form_fields=[_encode_form_field(f, participants) for f in tm.form_fields],
            form_fields_by_target={
                key: [_encode_form_field(f, participants) for f in fields]
                for key, fields in tm.form_fields_by_target.items()
            },
            sync_target_field=tm.sync_target_field,
            sync_field_status=tm.sync_field_status,
            sync_field_existing_value=tm.sync_field_existing_value,
            remembered_create_new=tm.remembered_create_new,
            remembered_dismissed=tm.remembered_dismissed,
        )
        for tm in analysis.text_mappings
    ]

    text_targets = [
        PublicWordImportTextTarget(
            template_element_id=_pub(template_elements, tt.template_element_id, "template_element"),
            block_sort_index=tt.block_sort_index,
            label=tt.label,
            is_event_repeat=tt.is_event_repeat,
            is_form_block=tt.is_form_block,
            form_rows=tt.form_rows,
        )
        for tt in analysis.text_targets
    ]

    attendance_mappings = [
        PublicWordImportAttendanceMapping(
            raw_name=am.raw_name,
            status=am.status,
            suggested_participant_id=_pub(participants, am.suggested_participant_id, "participant"),
            candidates=[_encode_attendance_candidate(c, participants) for c in am.candidates],
            remembered_no_link=am.remembered_no_link,
        )
        for am in analysis.attendance_mappings
    ]

    event_mappings = [
        PublicWordImportEventMapping(
            row_index=em.row_index,
            raw_title=em.raw_title,
            raw_date=em.raw_date,
            raw_end_date=em.raw_end_date,
            status=em.status,
            matched_event_id=_pub(events, em.matched_event_id, "event"),
            matched_event_title=em.matched_event_title,
            matched_event_date=em.matched_event_date,
            matched_event_end_date=em.matched_event_end_date,
            candidates=[_encode_event_candidate(c, events) for c in em.candidates],
            tag=em.tag,
            participant_count=em.participant_count,
            matrix_key=em.matrix_key,
            matrix_title=em.matrix_title,
            row_id=em.row_id,
            row_label=em.row_label,
            column_key=em.column_key,
            column_label=em.column_label,
            remembered_title_source=em.remembered_title_source,
            remembered_date_source=em.remembered_date_source,
            remembered_dismissed=em.remembered_dismissed,
        )
        for em in analysis.event_mappings
    ]

    list_definition_options = [
        PublicWordImportListDefinitionOption(
            id=_pub(list_definitions, ld.id, "list_definition"),
            name=ld.name,
        )
        for ld in analysis.list_definitions
    ]

    list_mappings = [
        PublicWordImportListRowMapping(
            table_index=lm.table_index,
            row_index=lm.row_index,
            column_one_raw=lm.column_one_raw,
            column_two_raw=lm.column_two_raw,
            column_one_type=lm.column_one_type,
            column_two_type=lm.column_two_type,
            status=lm.status,
            matched_entry_id=_pub(list_entries, lm.matched_entry_id, "list_entry"),
            column_one_names=[_encode_name_resolution(n, participants) for n in lm.column_one_names],
            column_two_names=[_encode_name_resolution(n, participants) for n in lm.column_two_names],
            candidates=[
                PublicWordImportListEntryCandidate(
                    entry_id=_pub(list_entries, c.entry_id, "list_entry"),
                    column_one_display=c.column_one_display,
                    column_two_display=c.column_two_display,
                    score=c.score,
                    reason=c.reason,
                )
                for c in lm.candidates
            ],
            has_snapshot_target=lm.has_snapshot_target,
            group_filled=lm.group_filled,
        )
        for lm in analysis.list_mappings
    ]

    matrix_mappings = [
        PublicWordImportMatrixCellMapping(
            table_index=mm.table_index,
            matrix_key=mm.matrix_key,
            matrix_title=mm.matrix_title,
            row_id=mm.row_id,
            row_label=mm.row_label,
            row_label_raw=mm.row_label_raw,
            row_type=mm.row_type,
            column_label_raw=mm.column_label_raw,
            column_key=mm.column_key,
            column_candidates=mm.column_candidates,
            raw_value=mm.raw_value,
            names=[_encode_name_resolution(n, participants) for n in mm.names],
        )
        for mm in analysis.matrix_mappings
    ]

    duplicate_protocols = [
        PublicWordImportDuplicateProtocol(
            id=_pub(protocols, dp.id, "protocol"),
            protocol_number=dp.protocol_number,
            title=dp.title,
            protocol_date=dp.protocol_date,
        )
        for dp in analysis.duplicate_protocols
    ]

    return PublicWordImportAnalysis(
        protocol_date=analysis.protocol_date,
        tables=tables,
        text_mappings=text_mappings,
        text_targets=text_targets,
        attendance_mappings=attendance_mappings,
        event_mappings=event_mappings,
        list_definitions=list_definition_options,
        list_mappings=list_mappings,
        matrix_options=analysis.matrix_options,
        matrix_mappings=matrix_mappings,
        profile_applied=analysis.profile_applied,
        warnings=analysis.warnings,
        duplicate_protocols=duplicate_protocols,
    )


def _encode_duplicate_candidate(
    db: Session, duplicate: WordImportDuplicateCandidate
) -> PublicWordImportDuplicateCandidate:
    documents = public_id_service.resolve_public_ids(db, WordImportDocument, [duplicate.id])
    protocols = (
        public_id_service.resolve_public_ids(db, Protocol, [duplicate.protocol_id])
        if duplicate.protocol_id is not None
        else {}
    )
    return PublicWordImportDuplicateCandidate(
        id=_pub(documents, duplicate.id, "word_import_document"),
        display_name=duplicate.display_name,
        original_filename=duplicate.original_filename,
        status=duplicate.status,
        protocol_id=_pub(protocols, duplicate.protocol_id, "protocol"),
    )


def _encode_summary(db: Session, summary: WordImportDocumentSummary) -> PublicWordImportDocumentSummary:
    documents = public_id_service.resolve_public_ids(db, WordImportDocument, [summary.id])
    templates = public_id_service.resolve_public_ids(db, Template, [summary.template_id])
    protocols = (
        public_id_service.resolve_public_ids(db, Protocol, [summary.protocol_id])
        if summary.protocol_id is not None
        else {}
    )
    stored_files = public_id_service.resolve_public_ids(db, StoredFile, [summary.stored_file_id])
    return PublicWordImportDocumentSummary(
        id=_pub(documents, summary.id, "word_import_document"),
        template_id=_pub(templates, summary.template_id, "template"),
        template_name=summary.template_name,
        display_name=summary.display_name,
        original_filename=summary.original_filename,
        status=summary.status,
        protocol_id=_pub(protocols, summary.protocol_id, "protocol"),
        protocol_date=summary.protocol_date,
        created_at=summary.created_at,
        imported_at=summary.imported_at,
        stored_file_id=_pub(stored_files, summary.stored_file_id, "stored_file"),
        duplicates=[_encode_duplicate_candidate(db, d) for d in summary.duplicates],
    )


# ---------------------------------------------------------------------------
# Decode direction: Public (uuid-id) -> internal (int-id) WordImport*. Used
# only for the incoming WordImportCommit request body, before calling
# service.commit()/queue_service.commit_document(). Security-sensitive: every
# resolution is scoped to tenant_id, and any UUID that fails to resolve within
# that tenant raises HTTPException(400) rather than passing through as None.
# ---------------------------------------------------------------------------


def _req(id_map: dict[uuid.UUID, int], public_id: uuid.UUID | None, field_name: str) -> int | None:
    if public_id is None:
        return None
    internal_id = id_map.get(public_id)
    if internal_id is None:
        raise HTTPException(status_code=400, detail=f"Unbekannte oder fremde Referenz: {field_name}")
    return internal_id


def _collect_commit_ids(
    payload: PublicWordImportCommit,
) -> tuple[set[uuid.UUID], set[uuid.UUID], set[uuid.UUID], set[uuid.UUID], set[uuid.UUID]]:
    template_element_ids: set[uuid.UUID] = set()
    event_ids: set[uuid.UUID] = set()
    participant_ids: set[uuid.UUID] = set()
    list_definition_ids: set[uuid.UUID] = set()
    list_entry_ids: set[uuid.UUID] = set()

    def collect_name(name: PublicWordImportNameResolution) -> None:
        if name.participant_id is not None:
            participant_ids.add(name.participant_id)
        if name.originally_suggested_participant_id is not None:
            participant_ids.add(name.originally_suggested_participant_id)
        for candidate in name.candidates:
            participant_ids.add(candidate.participant_id)

    for text in payload.texts:
        if text.template_element_id is not None:
            template_element_ids.add(text.template_element_id)
        if text.linked_event_id is not None:
            event_ids.add(text.linked_event_id)
        for field in text.form_fields:
            for name in field.names:
                collect_name(name)

    for attendance in payload.attendance:
        if attendance.participant_id is not None:
            participant_ids.add(attendance.participant_id)
        if attendance.originally_suggested_participant_id is not None:
            participant_ids.add(attendance.originally_suggested_participant_id)

    for event in payload.events:
        if event.linked_event_id is not None:
            event_ids.add(event.linked_event_id)
        if event.originally_suggested_event_id is not None:
            event_ids.add(event.originally_suggested_event_id)

    for row in payload.lists:
        list_definition_ids.add(row.list_definition_id)
        if row.linked_entry_id is not None:
            list_entry_ids.add(row.linked_entry_id)
        if row.originally_suggested_entry_id is not None:
            list_entry_ids.add(row.originally_suggested_entry_id)
        for name in row.column_one_names:
            collect_name(name)
        for name in row.column_two_names:
            collect_name(name)

    for cell in payload.matrices:
        for name in cell.names:
            collect_name(name)

    for table in payload.tables:
        if table.list_definition_id is not None:
            list_definition_ids.add(table.list_definition_id)

    return template_element_ids, event_ids, participant_ids, list_definition_ids, list_entry_ids


def _decode_name_resolution(
    name: PublicWordImportNameResolution, participants: dict[uuid.UUID, int]
) -> WordImportNameResolution:
    return WordImportNameResolution(
        raw_name=name.raw_name,
        participant_id=_req(participants, name.participant_id, "participant_id"),
        create_new=name.create_new,
        no_link=name.no_link,
        originally_suggested_participant_id=_req(
            participants, name.originally_suggested_participant_id, "originally_suggested_participant_id"
        ),
        originally_suggested_score=name.originally_suggested_score,
        candidates=[
            WordImportAttendanceCandidate(
                participant_id=_req(participants, c.participant_id, "candidates[].participant_id"),
                score=c.score,
                reason=c.reason,
            )
            for c in name.candidates
        ],
    )


def _decode_form_field(
    field: PublicWordImportFormFieldValue, participants: dict[uuid.UUID, int]
) -> WordImportFormFieldValue:
    return WordImportFormFieldValue(
        row_id=field.row_id,
        label=field.label,
        row_type=field.row_type,
        raw_value=field.raw_value,
        names=[_decode_name_resolution(n, participants) for n in field.names],
    )


def _decode_commit(db: Session, tenant_id: int, payload: PublicWordImportCommit) -> WordImportCommit:
    template_element_ids, event_ids, participant_ids, list_definition_ids, list_entry_ids = _collect_commit_ids(
        payload
    )

    template_id = _resolve_template_id(db, tenant_id, payload.template_id)
    template_elements = _resolve_template_element_ids(db, tenant_id, list(template_element_ids))
    events = public_id_service.resolve_internal_ids(db, Event, list(event_ids), tenant_id=tenant_id)
    participants = public_id_service.resolve_internal_ids(db, Participant, list(participant_ids), tenant_id=tenant_id)
    list_definitions = public_id_service.resolve_internal_ids(
        db, ListDefinition, list(list_definition_ids), tenant_id=tenant_id
    )
    list_entries = _resolve_list_entry_ids(db, tenant_id, list(list_entry_ids))

    texts = [
        WordImportTextCommit(
            extracted_heading=t.extracted_heading,
            content=t.content,
            template_element_id=_req(template_elements, t.template_element_id, "texts[].template_element_id"),
            block_sort_index=t.block_sort_index,
            is_event_repeat=t.is_event_repeat,
            linked_event_id=_req(events, t.linked_event_id, "texts[].linked_event_id"),
            is_form_block=t.is_form_block,
            form_fields=[_decode_form_field(f, participants) for f in t.form_fields],
            dismissed=t.dismissed,
            create_new=t.create_new,
            sync_field_source=t.sync_field_source,
        )
        for t in payload.texts
    ]

    attendance = [
        WordImportAttendanceCommit(
            raw_name=a.raw_name,
            participant_id=_req(participants, a.participant_id, "attendance[].participant_id"),
            participant_name=a.participant_name,
            status=a.status,
            create_new=a.create_new,
            originally_suggested_participant_id=_req(
                participants,
                a.originally_suggested_participant_id,
                "attendance[].originally_suggested_participant_id",
            ),
            originally_suggested_score=a.originally_suggested_score,
        )
        for a in payload.attendance
    ]

    events_commit = [
        WordImportEventCommit(
            approved=e.approved,
            linked_event_id=_req(events, e.linked_event_id, "events[].linked_event_id"),
            final_title=e.final_title,
            final_date=e.final_date,
            final_end_date=e.final_end_date,
            raw_title=e.raw_title,
            raw_date=e.raw_date,
            raw_end_date=e.raw_end_date,
            tag=e.tag,
            participant_count=e.participant_count,
            originally_suggested_event_id=_req(
                events, e.originally_suggested_event_id, "events[].originally_suggested_event_id"
            ),
            originally_suggested_score=e.originally_suggested_score,
        )
        for e in payload.events
    ]

    lists = [
        WordImportListRowCommit(
            table_index=row.table_index,
            list_definition_id=_req(list_definitions, row.list_definition_id, "lists[].list_definition_id"),
            column_one_raw=row.column_one_raw,
            column_two_raw=row.column_two_raw,
            column_one_names=[_decode_name_resolution(n, participants) for n in row.column_one_names],
            column_two_names=[_decode_name_resolution(n, participants) for n in row.column_two_names],
            approved=row.approved,
            linked_entry_id=_req(list_entries, row.linked_entry_id, "lists[].linked_entry_id"),
            originally_suggested_entry_id=_req(
                list_entries, row.originally_suggested_entry_id, "lists[].originally_suggested_entry_id"
            ),
            originally_suggested_score=row.originally_suggested_score,
        )
        for row in payload.lists
    ]

    matrices = [
        WordImportMatrixCellCommit(
            matrix_key=cell.matrix_key,
            row_id=cell.row_id,
            row_type=cell.row_type,
            column_key=cell.column_key,
            column_label=cell.column_label,
            column_label_raw=cell.column_label_raw,
            raw_value=cell.raw_value,
            names=[_decode_name_resolution(n, participants) for n in cell.names],
            approved=cell.approved,
            originally_suggested_column_key=cell.originally_suggested_column_key,
            originally_suggested_score=cell.originally_suggested_score,
        )
        for cell in payload.matrices
    ]

    tables = [
        WordImportTableRoleCommit(
            header_signature=table.header_signature,
            role=table.role,
            list_definition_id=_req(list_definitions, table.list_definition_id, "tables[].list_definition_id"),
            matrix_key=table.matrix_key,
            list_grouping_strategy=table.list_grouping_strategy,
            originally_suggested_role=table.originally_suggested_role,
            originally_suggested_score=table.originally_suggested_score,
        )
        for table in payload.tables
    ]

    return WordImportCommit(
        template_id=template_id,
        protocol_date=payload.protocol_date,
        texts=texts,
        attendance=attendance,
        events=events_commit,
        dismissed_events=payload.dismissed_events,
        lists=lists,
        matrices=matrices,
        tables=tables,
    )


def _encode_commit_result(db: Session, result: WordImportCommitResult) -> PublicWordImportCommitResult:
    protocols = public_id_service.resolve_public_ids(db, Protocol, [result.id])
    return PublicWordImportCommitResult(
        id=_pub(protocols, result.id, "protocol"),
        warnings=result.warnings,
    )


@router.post("/tools/word-import/analyze", response_model=PublicWordImportAnalysis)
async def analyze_word_import(
    file: UploadFile = File(...),
    template_id: uuid.UUID = Form(...),
    protocol_date_hint: date | None = Form(None),
    table_roles_json: str | None = Form(None),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    internal_template_id = _resolve_template_id(db, user.current_tenant_id, template_id)
    if not file.filename or not file.filename.lower().endswith((".docx", ".pdf")):
        raise HTTPException(status_code=400, detail="Nur .docx- oder .pdf-Dateien werden unterstützt")
    raw_bytes = await _read_upload_within_limit(file, MAX_UPLOAD_BYTES)
    if raw_bytes is None:
        raise HTTPException(status_code=413, detail=f"Datei zu gross. Maximum {MAX_UPLOAD_BYTES // 1024 // 1024} MB")
    table_role_overrides: dict[int, dict] = {}
    if table_roles_json:
        try:
            table_role_overrides = {int(key): value for key, value in json.loads(table_roles_json).items()}
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail="Ungültige Tabellen-Zuordnung") from exc
    try:
        # Ausgelagert in einen Threadpool-Worker statt direkt im Event-Loop ausgeführt -
        # WordImportService.analyze() ist eine synchrone Funktion, die u.a. das Parsen des
        # Dokuments anstösst (siehe parse_document_isolated() in word_import_service.py,
        # das seinerseits pathologische Dateien in einem eigenen, hart abbrechbaren
        # Subprozess parst). Ohne dieses Auslagern würde ein einziger blockierender
        # analyze()-Aufruf einen der nur zwei uvicorn-Worker-Prozesse für ALLE Mandanten
        # gleichzeitig blockieren.
        analysis = await run_in_threadpool(
            service.analyze,
            db,
            tenant_id=user.current_tenant_id,
            template_id=internal_template_id,
            protocol_date_hint=protocol_date_hint,
            raw_bytes=raw_bytes,
            table_role_overrides=table_role_overrides,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Datei konnte nicht gelesen werden") from exc
    return _encode_analysis(db, analysis)


@router.post("/tools/word-import/commit", response_model=PublicWordImportCommitResult, status_code=status.HTTP_201_CREATED)
def commit_word_import(
    payload: PublicWordImportCommit,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    internal_payload = _decode_commit(db, user.current_tenant_id, payload)
    try:
        result = service.commit(db, tenant_id=user.current_tenant_id, user_id=user.user_id, payload=internal_payload)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Protokoll konnte nicht erstellt werden") from exc
    return _encode_commit_result(db, result)


def _to_summary(
    document: WordImportDocument, template_name: str, duplicates: list[WordImportDocument] | None = None
) -> WordImportDocumentSummary:
    return WordImportDocumentSummary(
        id=document.id,
        template_id=document.template_id,
        template_name=template_name,
        display_name=document.display_name,
        original_filename=document.original_filename,
        status=document.status,
        protocol_id=document.protocol_id,
        protocol_date=document.protocol_date,
        created_at=document.created_at,
        imported_at=document.imported_at,
        stored_file_id=document.stored_file_id,
        duplicates=[WordImportDuplicateCandidate.model_validate(dup) for dup in duplicates or []],
    )


def _to_public_summary(
    db: Session,
    document: WordImportDocument,
    template_name: str,
    duplicates: list[WordImportDocument] | None = None,
) -> PublicWordImportDocumentSummary:
    return _encode_summary(db, _to_summary(document, template_name, duplicates))


@router.post("/tools/word-import/documents", response_model=PublicWordImportDocumentUploadResult, status_code=status.HTTP_201_CREATED)
async def ingest_word_import_documents(
    template_id: uuid.UUID = Form(...),
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    internal_template_id = _resolve_template_id(db, user.current_tenant_id, template_id)
    if len(files) > MAX_WORD_IMPORT_BATCH_FILES:
        raise HTTPException(
            status_code=413,
            detail=f"Zu viele Dateien in einem Batch (maximal {MAX_WORD_IMPORT_BATCH_FILES})",
        )

    file_payloads: list[tuple[str, bytes]] = []
    errors: list[str] = []
    batch_bytes = 0
    for file in files:
        name = file.filename or ""
        lower = name.lower()
        if batch_bytes > MAX_WORD_IMPORT_BATCH_BYTES:
            errors.append(f"{name or 'Datei'}: übersprungen - Gesamtgrösse des Batches überschritten")
            continue
        if lower.endswith(".zip"):
            zip_bytes = await _read_upload_within_limit(file, MAX_ZIP_TOTAL_BYTES)
            if zip_bytes is None:
                errors.append(f"{name}: ZIP-Datei zu gross (maximal {MAX_ZIP_TOTAL_BYTES // 1024 // 1024} MB)")
                continue
            # Unlike analyze()/ingest() below, this ran synchronously on the event loop -
            # a large batch ZIP (up to MAX_ZIP_TOTAL_BYTES) blocks every other tenant's
            # request on this worker for the whole decompression (audit finding,
            # 2026-08-25).
            matched, notes = await run_in_threadpool(extract_word_import_files_from_zip, zip_bytes)
            file_payloads.extend(matched)
            batch_bytes += sum(len(content) for _, content in matched)
            errors.extend(f"{name}: {note}" for note in notes)
            continue
        if not name or not lower.endswith((".docx", ".pdf")):
            errors.append(f"{name or 'Datei'}: Nur .docx-, .pdf- oder .zip-Dateien werden unterstützt")
            continue
        content = await _read_upload_within_limit(file, MAX_UPLOAD_BYTES)
        if content is None:
            errors.append(f"{name}: zu gross (maximal {MAX_UPLOAD_BYTES // 1024 // 1024} MB)")
            continue
        file_payloads.append((name, content))
        batch_bytes += len(content)

    try:
        # Siehe Kommentar bei analyze_word_import oben - queue_service.ingest() ruft
        # dieselbe synchrone analyze()-Kette für jede Datei des Batches nacheinander auf,
        # muss also ebenso aus dem Event-Loop ausgelagert werden.
        documents, ingest_errors = await run_in_threadpool(
            queue_service.ingest,
            db,
            tenant_id=user.current_tenant_id,
            template_id=internal_template_id,
            created_by=user.user_id,
            files=file_payloads,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    template = db.get(Template, internal_template_id)
    template_name = template.name if template else ""
    return PublicWordImportDocumentUploadResult(
        documents=[
            _to_public_summary(db, doc, template_name, queue_service.duplicates_for_document(db, doc))
            for doc in documents
        ],
        errors=errors + ingest_errors,
    )


@router.get("/tools/word-import/last-template", response_model=PublicWordImportLastTemplate)
def get_last_word_import_template(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    tenant = db.get(Tenant, user.current_tenant_id)
    internal_template_id = tenant.last_word_import_template_id if tenant else None
    template_public_id = (
        public_id_service.resolve_public_id(db, Template, internal_template_id)
        if internal_template_id is not None
        else None
    )
    return PublicWordImportLastTemplate(template_id=template_public_id)


@router.put("/tools/word-import/last-template", response_model=PublicWordImportLastTemplate)
def set_last_word_import_template(
    payload: PublicWordImportLastTemplate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    tenant = db.get(Tenant, user.current_tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Mandant nicht gefunden")
    internal_template_id = None
    if payload.template_id is not None:
        internal_template_id = public_id_service.resolve_internal_id(
            db, Template, payload.template_id, tenant_id=user.current_tenant_id
        )
        if internal_template_id is None:
            raise HTTPException(status_code=400, detail="Vorlage nicht gefunden")
    tenant.last_word_import_template_id = internal_template_id
    db.commit()
    template_public_id = (
        public_id_service.resolve_public_id(db, Template, internal_template_id)
        if internal_template_id is not None
        else None
    )
    return PublicWordImportLastTemplate(template_id=template_public_id)


@router.get("/tools/word-import/documents", response_model=list[PublicWordImportDocumentSummary])
def list_word_import_documents(
    status_filter: str | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    rows = queue_service.list_documents(db, tenant_id=user.current_tenant_id, status=status_filter)
    return [_to_public_summary(db, document, template_name, duplicates) for document, template_name, duplicates in rows]


@router.get("/tools/word-import/documents/{document_id}", response_model=PublicWordImportDocumentDetail)
def get_word_import_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    internal_document_id = _resolve_document_id(db, user.current_tenant_id, document_id)
    document = queue_service.get_document(db, tenant_id=user.current_tenant_id, document_id=internal_document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    template = db.get(Template, document.template_id)
    duplicates = queue_service.duplicates_for_document(db, document)
    summary = _to_summary(document, template.name if template else "", duplicates)
    detail = WordImportDocumentDetail(
        **summary.model_dump(),
        analysis=WordImportAnalysis(**document.analysis_snapshot_json),
        review_draft=document.review_draft_json,
    )
    public_summary = _encode_summary(db, summary)
    return PublicWordImportDocumentDetail(
        **public_summary.model_dump(),
        analysis=_encode_analysis(db, detail.analysis),
        review_draft=detail.review_draft,
    )


@router.put("/tools/word-import/documents/{document_id}/draft", response_model=dict[str, str])
def save_word_import_document_draft(
    document_id: uuid.UUID,
    payload: WordImportDraftSave,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    internal_document_id = _resolve_document_id(db, user.current_tenant_id, document_id)
    document = queue_service.get_document(db, tenant_id=user.current_tenant_id, document_id=internal_document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    try:
        queue_service.save_draft(db, document=document, draft=payload.draft)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"message": "Entwurf gespeichert"}


@router.post("/tools/word-import/documents/{document_id}/reanalyze", response_model=PublicWordImportAnalysis)
def reanalyze_word_import_document(
    document_id: uuid.UUID,
    payload: WordImportDocumentReanalyzeRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    internal_document_id = _resolve_document_id(db, user.current_tenant_id, document_id)
    document = queue_service.get_document(db, tenant_id=user.current_tenant_id, document_id=internal_document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    try:
        analysis = queue_service.reanalyze(
            db, document=document, protocol_date=payload.protocol_date, table_role_overrides=payload.table_roles
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _encode_analysis(db, analysis)


@router.post("/tools/word-import/documents/{document_id}/commit", response_model=PublicWordImportCommitResult, status_code=status.HTTP_201_CREATED)
def commit_word_import_document(
    document_id: uuid.UUID,
    payload: PublicWordImportCommit,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    internal_document_id = _resolve_document_id(db, user.current_tenant_id, document_id)
    document = queue_service.get_document(db, tenant_id=user.current_tenant_id, document_id=internal_document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    internal_payload = _decode_commit(db, user.current_tenant_id, payload)
    try:
        result = queue_service.commit_document(
            db, document=document, tenant_id=user.current_tenant_id, user_id=user.user_id, payload=internal_payload
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Protokoll konnte nicht erstellt werden") from exc
    return _encode_commit_result(db, result)


@router.delete("/tools/word-import/documents/{document_id}", response_model=dict[str, str])
def delete_word_import_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    internal_document_id = _resolve_document_id(db, user.current_tenant_id, document_id)
    try:
        deleted = queue_service.delete_document(db, tenant_id=user.current_tenant_id, document_id=internal_document_id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    return {"message": "Dokument entfernt"}


@router.get("/tools/word-import/quality-stats", response_model=WordImportQualityStats)
def get_word_import_quality_stats(
    template_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    internal_template_id = None
    if template_id is not None:
        internal_template_id = _resolve_template_id(db, user.current_tenant_id, template_id)
    buckets = quality_service.accept_rate_stats(db, tenant_id=user.current_tenant_id, template_id=internal_template_id)
    return WordImportQualityStats(buckets=[WordImportQualityBucket(**bucket) for bucket in buckets])
