"""Tests for the "Pro Termin" block <-> Termin field sync feature (block_field_sync.py):
a text block with a configured sync_target_field mirrors its content into a column of
its linked Event, both when a user edits it live (autosave_service.save_text_block)
and when the Word importer writes it (WordImportService.analyze()/commit()) - with the
importer asking which side wins whenever the Event's field already holds a different
value (see WordImportTextMapping.sync_field_status / WordImportTextCommit.sync_field_source).
"""
from datetime import date

from sqlalchemy import select

from app.models import ProtocolElement, ProtocolElementBlock
from app.schemas.protocol import ProtocolCreateFromTemplate
from app.schemas.word_import import WordImportCommit, WordImportTextCommit
from app.services import block_field_sync
from app.services.autosave_service import AutosaveService
from app.services.protocol_service import ProtocolService
from app.services.word_import_service import WordImportService
from tests.factories import (
    element_type_id,
    make_element_definition,
    make_event,
    make_protocol_todo,
    make_template,
    make_template_element,
    make_tenant,
)
from tests.word_import_fixtures import TableSpec, TextSpec, default_spec, render_docx

RENDER_TYPE_PARAGRAPH = 2


def _build_rueckblick_template(db, *, sync_target_field: str | None = "description"):
    """A minimal template with a single "Rückblick" event-repeat text block, configured
    with the given sync_target_field - mirrors the "Rückblick" element from
    test_word_import_e2e.py's _build_template, trimmed to just what these tests need."""
    tenant = make_tenant(db)
    template = make_template(db, tenant.id, name="Hock-Protokoll")
    template.protocol_number_pattern = "P-{n}"
    db.flush()

    herbsthock = make_event(db, tenant.id, title="Herbsthock", event_date=date(2026, 10, 18))

    text_type = element_type_id(db, "text")
    definition = make_element_definition(
        db, tenant.id, "Rückblick",
        blocks=[{
            "id": 1, "title": "Rückblick", "description": None, "block_title": None,
            "default_content": "", "copy_from_last_protocol": False,
            "element_type_id": text_type, "render_type_id": RENDER_TYPE_PARAGRAPH,
            "is_editable": True, "allows_multiple_values": False, "export_visible": True, "is_visible": True,
            "sort_index": 10, "render_order": 10, "latex_template": None,
            "configuration_json": {"repeat_source": "event", "sync_target_field": sync_target_field},
        }],
    )
    template_element = make_template_element(db, template.id, definition.id, sort_index=10, section_name="Rückblick")

    return {"tenant": tenant, "template": template, "event": herbsthock, "template_element": template_element}


def _minimal_rueckblick_docx() -> bytes:
    """default_spec() minus every table/section this template doesn't have a target
    for - _add_table/_add_text both skip a spec with no rows/lines, so only the
    "Rückblick Herbsthock" heading/paragraphs actually end up in the document."""
    spec = default_spec()
    spec.attendance = TableSpec(heading="Anwesenheit", header_cells=[], rows=[])
    spec.events = TableSpec(heading="Termine", header_cells=[], rows=[])
    spec.list_table = TableSpec(heading="Ämtli", header_cells=[], rows=[])
    spec.matrix = TableSpec(heading="Anwesenheitsmatrix", header_cells=[], rows=[])
    spec.form_text = TextSpec(heading="Scharanlässe", lines=[])
    return render_docx(spec)


def test_apply_text_sync_writes_configured_event_field(db):
    tenant = make_tenant(db)
    event = make_event(db, tenant.id, title="Herbsthock", event_date=date(2026, 10, 18))

    block_field_sync.apply_text_sync(
        db, repeat_source_type="event", repeat_source_id=event.id, sync_target_field="location", content="Vereinshaus"
    )

    db.flush()
    assert event.location == "Vereinshaus"


def test_apply_text_sync_writes_configured_todo_field(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    db.flush()
    # protocol_element_block_id is never dereferenced by apply_text_sync - only the
    # ProtocolTodo row's own id matters, so no protocol scaffolding is needed here.
    todo = make_protocol_todo(db, protocol_element_block_id=None, task="Alter Text", tenant_id=tenant.id)

    block_field_sync.apply_text_sync(
        db, repeat_source_type="todo", repeat_source_id=todo.id, sync_target_field="reference_link", content="https://example.org"
    )

    db.flush()
    assert todo.reference_link == "https://example.org"


def test_apply_text_sync_ignores_field_outside_allowlist(db):
    """A stale/manipulated sync_target_field (e.g. left over after repeat_source was
    switched, or never validated) must never let arbitrary columns be overwritten."""
    tenant = make_tenant(db)
    event = make_event(db, tenant.id, title="Herbsthock", event_date=date(2026, 10, 18))

    block_field_sync.apply_text_sync(
        db, repeat_source_type="event", repeat_source_id=event.id, sync_target_field="tenant_id", content="not-a-real-write"
    )

    db.flush()
    assert event.tenant_id == tenant.id


def test_apply_text_sync_noop_without_sync_target_field(db):
    tenant = make_tenant(db)
    event = make_event(db, tenant.id, title="Herbsthock", event_date=date(2026, 10, 18))

    block_field_sync.apply_text_sync(
        db, repeat_source_type="event", repeat_source_id=event.id, sync_target_field=None, content="Should not land anywhere"
    )

    db.flush()
    assert event.description is None


def test_save_text_block_syncs_to_linked_event_field(db):
    """The live-editing path (autosave_service.save_text_block, wired up in
    protocol_elements.py's PUT .../text route) writes through to the Event field
    exactly like block_field_sync.apply_text_sync does directly."""
    ctx = _build_rueckblick_template(db, sync_target_field="location")
    protocol_service = ProtocolService()
    # protocol_date chosen inside the block's default relative window (event_date <=
    # protocol_date + 14 days, event_end_date >= protocol_date - see
    # ProtocolService._event_repeat_contexts) so create_from_template auto-generates
    # the Rückblick block for Herbsthock (2026-10-18) without any manual wiring.
    protocol_id = protocol_service.create_from_template(
        db,
        ProtocolCreateFromTemplate(template_id=ctx["template"].id, protocol_date=date(2026, 10, 10), event_id=None),
        tenant_id=ctx["tenant"].id, created_by=None,
    )
    db.flush()
    block = db.execute(
        select(ProtocolElementBlock)
        .join(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
        .where(ProtocolElement.protocol_id == protocol_id)
    ).scalars().one()

    autosave_service = AutosaveService()
    autosave_service.save_text_block(
        db, block.id, "Neuer Standort laut Protokoll", block_config=block.configuration_snapshot_json
    )

    db.flush()
    assert ctx["event"].location == "Neuer Standort laut Protokoll"


def test_analyze_flags_empty_event_field_without_conflict(db):
    ctx = _build_rueckblick_template(db, sync_target_field="description")
    assert ctx["event"].description is None

    analysis = WordImportService().analyze(
        db, tenant_id=ctx["tenant"].id, template_id=ctx["template"].id,
        protocol_date_hint=date(2026, 10, 20), raw_bytes=_minimal_rueckblick_docx(),
    )

    mapping = next(m for m in analysis.text_mappings if m.is_event_repeat)
    assert mapping.matched_event_id == ctx["event"].id
    assert mapping.sync_target_field == "description"
    assert mapping.sync_field_status == "empty"
    assert mapping.sync_field_existing_value is None


def test_analyze_flags_conflict_when_event_field_already_differs(db):
    ctx = _build_rueckblick_template(db, sync_target_field="description")
    ctx["event"].description = "Ganz anderer Text, der nicht im Dokument vorkommt."
    db.flush()

    analysis = WordImportService().analyze(
        db, tenant_id=ctx["tenant"].id, template_id=ctx["template"].id,
        protocol_date_hint=date(2026, 10, 20), raw_bytes=_minimal_rueckblick_docx(),
    )

    mapping = next(m for m in analysis.text_mappings if m.is_event_repeat)
    assert mapping.sync_field_status == "conflict"
    assert mapping.sync_field_existing_value == "Ganz anderer Text, der nicht im Dokument vorkommt."


def test_analyze_reports_match_when_event_field_already_equals_document_text(db):
    ctx = _build_rueckblick_template(db, sync_target_field="description")
    service = WordImportService()
    raw_bytes = _minimal_rueckblick_docx()

    # First pass just to learn the exact extracted text the parser produces for this
    # document, so the "already equal" case doesn't need to hardcode the parser's
    # markdown formatting.
    first_pass = service.analyze(
        db, tenant_id=ctx["tenant"].id, template_id=ctx["template"].id,
        protocol_date_hint=date(2026, 10, 20), raw_bytes=raw_bytes,
    )
    extracted = next(m for m in first_pass.text_mappings if m.is_event_repeat).extracted_text.strip()
    ctx["event"].description = extracted
    db.flush()

    second_pass = service.analyze(
        db, tenant_id=ctx["tenant"].id, template_id=ctx["template"].id,
        protocol_date_hint=date(2026, 10, 20), raw_bytes=raw_bytes,
    )
    mapping = next(m for m in second_pass.text_mappings if m.is_event_repeat)
    assert mapping.sync_field_status == "match"
    assert mapping.sync_field_existing_value is None


def test_commit_keeps_existing_event_value_when_reviewer_picks_existing(db):
    ctx = _build_rueckblick_template(db, sync_target_field="description")
    ctx["event"].description = "Bestehender Text, der bleiben soll."
    db.flush()

    result = WordImportService().commit(
        db, tenant_id=ctx["tenant"].id, user_id=None,
        payload=WordImportCommit(
            template_id=ctx["template"].id,
            protocol_date=date(2026, 10, 10),
            texts=[
                WordImportTextCommit(
                    extracted_heading="Rückblick Herbsthock",
                    content="Text aus dem Dokument, der verworfen wird.",
                    template_element_id=ctx["template_element"].id,
                    block_sort_index=10,
                    is_event_repeat=True,
                    linked_event_id=ctx["event"].id,
                    sync_field_source="existing",
                )
            ],
        ),
    )

    assert result.warnings == []
    db.flush()
    assert ctx["event"].description == "Bestehender Text, der bleiben soll."


def test_commit_overwrites_event_value_when_reviewer_picks_doc(db):
    ctx = _build_rueckblick_template(db, sync_target_field="description")
    ctx["event"].description = "Alter Text, der überschrieben wird."
    db.flush()

    WordImportService().commit(
        db, tenant_id=ctx["tenant"].id, user_id=None,
        payload=WordImportCommit(
            template_id=ctx["template"].id,
            protocol_date=date(2026, 10, 10),
            texts=[
                WordImportTextCommit(
                    extracted_heading="Rückblick Herbsthock",
                    content="Neuer Text aus dem Dokument.",
                    template_element_id=ctx["template_element"].id,
                    block_sort_index=10,
                    is_event_repeat=True,
                    linked_event_id=ctx["event"].id,
                    sync_field_source="doc",
                )
            ],
        ),
    )

    db.flush()
    assert ctx["event"].description == "Neuer Text aus dem Dokument."


def test_commit_writes_event_field_without_conflict_when_it_was_empty(db):
    ctx = _build_rueckblick_template(db, sync_target_field="location")
    assert ctx["event"].location is None

    WordImportService().commit(
        db, tenant_id=ctx["tenant"].id, user_id=None,
        payload=WordImportCommit(
            template_id=ctx["template"].id,
            protocol_date=date(2026, 10, 10),
            texts=[
                WordImportTextCommit(
                    extracted_heading="Rückblick Herbsthock",
                    content="Vereinshaus Musterdorf",
                    template_element_id=ctx["template_element"].id,
                    block_sort_index=10,
                    is_event_repeat=True,
                    linked_event_id=ctx["event"].id,
                    sync_field_source=None,
                )
            ],
        ),
    )

    db.flush()
    assert ctx["event"].location == "Vereinshaus Musterdorf"
