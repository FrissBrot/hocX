"""Regression test for H14 from the 2026-08-12 full audit: an edited "Pro Termin" wizard
text was written straight to the linked Event field at commit() time without ever
recomputing WordImportTextMapping.sync_field_status against the (possibly edited) text
actually being committed - only against the original document text analyze() saw. A
small wizard edit made after analyze() ran (e.g. fixing a typo) could therefore silently
overwrite a DB field the conflict-detection UI never actually evaluated.

Fix: backend/app/services/word_import_service.py's commit(), in the text_commit loop
around the ProtocolText branch - freshly re-reads the linked Event's current field value
at commit time and re-compares it against the content actually being committed (not the
stale analyze()-time comparison). If a conflict is found and the reviewer never gave an
explicit "doc"/"existing" resolution for it, the fix falls back to keeping the Event's
current value (same safe default the "existing" branch already uses) instead of silently
overwriting it, and appends a commit warning - mirroring the validate-at-commit-time
pattern event_commit already applies to title/date conflicts.
"""
from __future__ import annotations

from datetime import date

from app.schemas.word_import import WordImportCommit, WordImportTextCommit
from app.services.word_import_service import WordImportService
from tests.word_import_fixtures import default_spec, render_docx, TableSpec, TextSpec

RENDER_TYPE_PARAGRAPH = 2


def _build_rueckblick_template(db, *, sync_target_field: str = "description"):
    """Same minimal "Rückblick" event-repeat text block template as
    test_word_import_field_sync.py's helper of the same name, duplicated here so this
    regression test file stands alone."""
    from tests.factories import (
        element_type_id,
        make_element_definition,
        make_event,
        make_template,
        make_template_element,
        make_tenant,
    )

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
    spec = default_spec()
    spec.attendance = TableSpec(heading="Anwesenheit", header_cells=[], rows=[])
    spec.events = TableSpec(heading="Termine", header_cells=[], rows=[])
    spec.list_table = TableSpec(heading="Ämtli", header_cells=[], rows=[])
    spec.matrix = TableSpec(heading="Anwesenheitsmatrix", header_cells=[], rows=[])
    spec.form_text = TextSpec(heading="Scharanlässe", lines=[])
    return render_docx(spec)


def test_h14_edited_wizard_text_does_not_silently_overwrite_event_field(db):
    """analyze() sees the document text already matching the Event's current field value
    (status "match", no conflict flagged, so the wizard never shows a resolution UI and
    sync_field_source stays unset). The reviewer then edits the wizard text before
    committing - the edited text must NOT be blindly written into the Event field: since
    that specific conflict (edited text vs. current DB value) was never actually
    confirmed by the reviewer, the safe existing DB value must be kept and a warning
    surfaced, exactly like the pre-existing "existing" resolution branch already does."""
    ctx = _build_rueckblick_template(db, sync_target_field="description")
    service = WordImportService()
    raw_bytes = _minimal_rueckblick_docx()

    # Learn the parser's exact extracted text, then seed the Event field with the same
    # value so a second analyze() pass reports sync_field_status == "match" (no conflict).
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

    edited_text = "Vom Benutzer im Assistenten bearbeiteter Text, der vom Dokument abweicht."
    assert edited_text != extracted

    result = service.commit(
        db, tenant_id=ctx["tenant"].id, user_id=None,
        payload=WordImportCommit(
            template_id=ctx["template"].id,
            protocol_date=date(2026, 10, 10),
            texts=[
                WordImportTextCommit(
                    extracted_heading=mapping.extracted_heading,
                    content=edited_text,
                    template_element_id=mapping.template_element_id,
                    block_sort_index=mapping.block_sort_index,
                    is_event_repeat=True,
                    linked_event_id=mapping.matched_event_id,
                    # No explicit resolution was ever presented to (or made by) the
                    # reviewer for this conflict - analyze() reported "match", not
                    # "conflict", so the wizard never asked.
                    sync_field_source=None,
                )
            ],
        ),
    )

    db.flush()
    # The Event field must still hold its original (pre-edit) value - the edit was never
    # validated against it, so it must not silently land in the DB.
    assert ctx["event"].description == extracted
    assert ctx["event"].description != edited_text
    # A warning must surface so the reviewer knows their edit wasn't synced to the Termin.
    assert any("description" in w and "nicht überschrieben" in w for w in result.warnings)


def test_h14_explicit_doc_resolution_still_overwrites_event_field(db):
    """Sanity check that the fix doesn't just block every edit: when the reviewer
    explicitly resolved a conflict in favor of the document text (sync_field_source ==
    "doc"), the committed content must still win, exactly as before this fix."""
    ctx = _build_rueckblick_template(db, sync_target_field="description")
    ctx["event"].description = "Alter Text, der überschrieben werden soll."
    db.flush()

    result = WordImportService().commit(
        db, tenant_id=ctx["tenant"].id, user_id=None,
        payload=WordImportCommit(
            template_id=ctx["template"].id,
            protocol_date=date(2026, 10, 10),
            texts=[
                WordImportTextCommit(
                    extracted_heading="Rückblick Herbsthock",
                    content="Neuer, vom Reviewer bestätigter Text.",
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
    assert ctx["event"].description == "Neuer, vom Reviewer bestätigter Text."
    assert result.warnings == []
