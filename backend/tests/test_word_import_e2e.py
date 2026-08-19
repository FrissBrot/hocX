"""End-to-end tests for the Word-Import pipeline: real .docx/.pdf bytes (built by
word_import_fixtures.py) through parse_document -> WordImportService.analyze() ->
a WordImportCommit built the same way the review wizard would (accepting analyze()'s
own top suggestions, with a couple of explicit "create new" choices for names that
can't possibly auto-match) -> WordImportService.commit() -> assertions against the
resulting DB rows (Protocol/ProtocolElementBlock/Event/Participant).

Goal: verify every table/section kind the importer supports (Anwesenheit, Termine,
a List, a Matrix, a form block, an event-repeat text block) actually lands the right
data end to end, for both supported file formats, not just that analyze() proposes
plausible-looking mappings.
"""
from datetime import date

import pytest
from sqlalchemy import select

from app.models import (
    Event,
    ListEntry,
    Participant,
    Protocol,
    ProtocolElement,
    ProtocolElementBlock,
    ProtocolText,
    WordImportProfile,
)
from app.schemas.word_import import (
    WordImportAttendanceCommit,
    WordImportCommit,
    WordImportEventCommit,
    WordImportFormFieldValue,
    WordImportListRowCommit,
    WordImportMatrixCellCommit,
    WordImportNameResolution,
    WordImportTableRoleCommit,
    WordImportTextCommit,
)
from app.services.word_import_service import WordImportService, parse_document

from tests.factories import (
    element_type_id,
    make_element_definition,
    make_event,
    make_list_definition,
    make_list_entry,
    make_participant,
    make_template,
    make_template_element,
    make_template_participant,
    make_tenant,
)
from tests.word_import_fixtures import default_spec, render_docx, render_pdf

RENDER_TYPE_KEY_VALUE = 5
RENDER_TYPE_PARAGRAPH = 2


def _build_template(db):
    """A template wired up with one target of every kind the importer supports:
    an attendance block, a list-linked block (Ämtli), a Matrix block, a plain
    "Scharanlässe"-style form block, and an event-repeat ("Rückblick") text block."""
    tenant = make_tenant(db)
    template = make_template(db, tenant.id, name="Hock-Protokoll")
    template.protocol_number_pattern = "P-{n}"
    db.flush()

    timo = make_participant(db, tenant.id, "Timo Weber")
    nevio = make_participant(db, tenant.id, "Nevio Muster")
    sandro = make_participant(db, tenant.id, "Sandro Keller")
    for participant in (timo, nevio, sandro):
        make_template_participant(db, template.id, participant.id)

    herbsthock = make_event(db, tenant.id, title="Herbsthock", event_date=date(2026, 10, 18))
    vorstandssitzung = make_event(db, tenant.id, title="Vorstandssitzung", event_date=date(2026, 10, 20))

    amtli = make_list_definition(
        db, tenant.id, name="Ämtli",
        column_one_title="Amt", column_one_value_type="text",
        column_two_title="Person", column_two_value_type="participant",
    )
    existing_feuer_entry = make_list_entry(
        db, amtli.id, sort_index=0,
        column_one_value={"text_value": "Feuer"},
        column_two_value={"participant_id": nevio.id},  # deliberately different from the doc -> "changed"
    )

    attendance_type = element_type_id(db, "attendance")
    form_type = element_type_id(db, "form")
    text_type = element_type_id(db, "text")
    matrix_type = element_type_id(db, "matrix")

    attendance_def = make_element_definition(
        db, tenant.id, "Anwesenheit",
        blocks=[{
            "id": 1, "title": "Anwesenheit", "description": None, "block_title": None,
            "default_content": "", "copy_from_last_protocol": False,
            "element_type_id": attendance_type, "render_type_id": RENDER_TYPE_KEY_VALUE,
            "is_editable": True, "allows_multiple_values": False, "export_visible": True, "is_visible": True,
            "sort_index": 10, "render_order": 10, "latex_template": None,
            "configuration_json": {},
        }],
    )
    make_template_element(db, template.id, attendance_def.id, sort_index=10, section_name="Anwesenheit")

    amtli_def = make_element_definition(
        db, tenant.id, "Ämtli",
        blocks=[{
            "id": 1, "title": "Ämtli", "description": None, "block_title": None,
            "default_content": "", "copy_from_last_protocol": False,
            "element_type_id": form_type, "render_type_id": RENDER_TYPE_KEY_VALUE,
            "is_editable": True, "allows_multiple_values": False, "export_visible": True, "is_visible": True,
            "sort_index": 10, "render_order": 10, "latex_template": None,
            "configuration_json": {"linked_list_id": amtli.id, "rows": []},
        }],
    )
    make_template_element(db, template.id, amtli_def.id, sort_index=20, section_name="Ämtli")

    scharanlaesse_def = make_element_definition(
        db, tenant.id, "Scharanlässe",
        blocks=[{
            "id": 1, "title": "Scharanlässe", "description": None, "block_title": None,
            "default_content": "", "copy_from_last_protocol": False,
            "element_type_id": form_type, "render_type_id": RENDER_TYPE_KEY_VALUE,
            "is_editable": True, "allows_multiple_values": False, "export_visible": True, "is_visible": True,
            "sort_index": 10, "render_order": 10, "latex_template": None,
            "configuration_json": {
                "linked_list_id": None,
                "rows": [
                    {"id": "r_treff", "label": "Treffpunkt", "row_type": "text", "template_value": "", "sort_index": 10},
                    {"id": "r_org", "label": "Organisation", "row_type": "participant", "template_participant_id": None, "sort_index": 20},
                    {"id": "r_wer", "label": "Wer geht", "row_type": "participants", "template_participant_ids": [], "sort_index": 30},
                ],
            },
        }],
    )
    make_template_element(db, template.id, scharanlaesse_def.id, sort_index=30, section_name="Scharanlässe")

    rueckblick_def = make_element_definition(
        db, tenant.id, "Rückblick",
        blocks=[{
            "id": 1, "title": "Rückblick", "description": None, "block_title": None,
            "default_content": "", "copy_from_last_protocol": False,
            "element_type_id": text_type, "render_type_id": RENDER_TYPE_PARAGRAPH,
            "is_editable": True, "allows_multiple_values": False, "export_visible": True, "is_visible": True,
            "sort_index": 10, "render_order": 10, "latex_template": None,
            "configuration_json": {"repeat_source": "event"},
        }],
    )
    make_template_element(db, template.id, rueckblick_def.id, sort_index=40, section_name="Rückblick")

    matrix_def = make_element_definition(
        db, tenant.id, "Anwesenheitsmatrix",
        blocks=[{
            "id": 1, "title": "Anwesenheitsmatrix", "description": None, "block_title": None,
            "default_content": "", "copy_from_last_protocol": False,
            "element_type_id": matrix_type, "render_type_id": RENDER_TYPE_KEY_VALUE,
            "is_editable": True, "allows_multiple_values": False, "export_visible": True, "is_visible": True,
            "sort_index": 10, "render_order": 10, "latex_template": None,
            "configuration_json": {
                "mode": "manual",
                "auto_source": {},
                "rows": [{"id": "row1", "label": "Küchendienst", "row_type": "participants", "row_config": {}, "sort_index": 10}],
                "columns": [
                    {"id": "col1", "title": "18.10.2026", "event_tag_filter": None, "sort_index": 10, "row_overrides": {}},
                    {"id": "col2", "title": "25.10.2026", "event_tag_filter": None, "sort_index": 20, "row_overrides": {}},
                ],
            },
        }],
    )
    make_template_element(db, template.id, matrix_def.id, sort_index=50, section_name="Anwesenheitsmatrix")

    return {
        "tenant": tenant,
        "template": template,
        "participants": {"Timo Weber": timo, "Nevio Muster": nevio, "Sandro Keller": sandro},
        "events": {"Herbsthock": herbsthock, "Vorstandssitzung": vorstandssitzung},
        "amtli": amtli,
        "existing_feuer_entry": existing_feuer_entry,
    }


def _commit_payload_from_analysis(analysis, *, template_id) -> WordImportCommit:
    """Mimics a user clicking through the review wizard and accepting every
    auto-suggestion as-is, with two deliberate exceptions the wizard would require a
    manual "als neu anlegen" click for (Ganz Neue Person has no roster match at all,
    neither in attendance nor in the Scharanlässe 'Wer geht' row)."""
    texts = []
    for mapping in analysis.text_mappings:
        form_fields = []
        for field in mapping.form_fields:
            names = []
            for name in field.names:
                if name.participant_id is None and name.raw_name.strip() == "Ganz Neue Person":
                    names.append(name.model_copy(update={"create_new": True}))
                else:
                    names.append(name)
            form_fields.append(WordImportFormFieldValue(**{**field.model_dump(exclude={"names"}), "names": names}))
        texts.append(
            WordImportTextCommit(
                extracted_heading=mapping.extracted_heading,
                content=mapping.extracted_text,
                template_element_id=mapping.template_element_id,
                block_sort_index=mapping.block_sort_index,
                is_event_repeat=mapping.is_event_repeat,
                linked_event_id=mapping.matched_event_id,
                is_form_block=mapping.is_form_block,
                form_fields=form_fields,
            )
        )

    attendance = []
    for mapping in analysis.attendance_mappings:
        create_new = mapping.suggested_participant_id is None and mapping.raw_name.strip() == "Ganz Neue Person"
        attendance.append(
            WordImportAttendanceCommit(
                raw_name=mapping.raw_name,
                participant_id=mapping.suggested_participant_id,
                participant_name=mapping.raw_name or "",
                status=mapping.status,
                create_new=create_new,
                originally_suggested_participant_id=mapping.suggested_participant_id,
                originally_suggested_score=(mapping.candidates[0].score if mapping.candidates else None),
            )
        )

    events = [
        WordImportEventCommit(
            approved=True,
            linked_event_id=mapping.matched_event_id,
            final_title=mapping.raw_title,
            final_date=mapping.raw_date,
            raw_title=mapping.raw_title,
            raw_date=mapping.raw_date,
            tag=mapping.tag,
            participant_count=mapping.participant_count,
            originally_suggested_event_id=mapping.matched_event_id,
            originally_suggested_score=(mapping.candidates[0].score if mapping.candidates else None),
        )
        for mapping in analysis.event_mappings
    ]

    lists = [
        WordImportListRowCommit(
            table_index=mapping.table_index,
            list_definition_id=next(t.list_definition_id for t in analysis.tables if t.index == mapping.table_index),
            column_one_raw=mapping.column_one_raw,
            column_two_raw=mapping.column_two_raw,
            column_one_names=mapping.column_one_names,
            column_two_names=mapping.column_two_names,
            approved=True,
            linked_entry_id=mapping.matched_entry_id,
            originally_suggested_entry_id=mapping.matched_entry_id,
            originally_suggested_score=(mapping.candidates[0].score if mapping.candidates else None),
        )
        for mapping in analysis.list_mappings
    ]

    matrices = [
        WordImportMatrixCellCommit(
            matrix_key=mapping.matrix_key,
            row_id=mapping.row_id,
            row_type=mapping.row_type,
            column_key=mapping.column_key,
            column_label=mapping.column_label_raw,
            column_label_raw=mapping.column_label_raw,
            raw_value=mapping.raw_value,
            names=mapping.names,
            approved=mapping.column_key is not None,
            originally_suggested_column_key=mapping.column_key,
            originally_suggested_score=(mapping.column_candidates[0].score if mapping.column_candidates else None),
        )
        for mapping in analysis.matrix_mappings
    ]

    tables = [
        WordImportTableRoleCommit(
            header_signature="|".join(t.header_cells),
            role=t.role,
            list_definition_id=t.list_definition_id,
            matrix_key=t.matrix_key,
            list_grouping_strategy=t.grouping_strategy,
            originally_suggested_role=t.role,
            originally_suggested_score=1.0 if t.role_is_explicit else None,
        )
        for t in analysis.tables
    ]

    return WordImportCommit(
        template_id=template_id,
        protocol_date=analysis.protocol_date,
        texts=texts,
        attendance=attendance,
        events=events,
        lists=lists,
        matrices=matrices,
        tables=tables,
    )


def _run_full_import(db, raw_bytes: bytes) -> tuple[dict, WordImportCommit, int]:
    ctx = _build_template(db)
    service = WordImportService()
    analysis = service.analyze(
        db, tenant_id=ctx["tenant"].id, template_id=ctx["template"].id,
        protocol_date_hint=None, raw_bytes=raw_bytes,
    )
    ctx["analysis"] = analysis
    payload = _commit_payload_from_analysis(analysis, template_id=ctx["template"].id)
    result = service.commit(db, tenant_id=ctx["tenant"].id, user_id=1, payload=payload)
    return ctx, payload, result.id


def _block_by_section(db, protocol_id: int, section_name: str) -> ProtocolElementBlock:
    return db.execute(
        select(ProtocolElementBlock)
        .join(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
        .where(ProtocolElement.protocol_id == protocol_id, ProtocolElement.section_name_snapshot == section_name)
    ).scalars().one()


def _assert_full_import(db, ctx, protocol_id):
    tenant = ctx["tenant"]
    participants = ctx["participants"]
    analysis = ctx["analysis"]

    # --- protocol_date + table role detection -------------------------------------
    assert analysis.protocol_date == date(2026, 10, 18)
    roles_by_header = {tuple(t.header_cells): t.role for t in analysis.tables}
    assert roles_by_header[("Name", "Status")] == "attendance"
    assert roles_by_header[("Datum", "Anlass")] == "events"
    assert roles_by_header[("Amt", "Person")] == "list"
    assert roles_by_header[("", "18.10.2026", "25.10.2026")] == "matrix"

    protocol = db.get(Protocol, protocol_id)
    assert protocol.protocol_date == date(2026, 10, 18)
    assert protocol.status == "abgeschlossen"

    # --- Anwesenheit -----------------------------------------------------------
    attendance_block = _block_by_section(db, protocol_id, "Anwesenheit")
    entries_by_id = {e["participant_id"]: e for e in attendance_block.configuration_snapshot_json["attendance_entries"]}
    assert entries_by_id[participants["Timo Weber"].id]["status"] == "present"
    assert entries_by_id[participants["Nevio Muster"].id]["status"] == "excused"
    # Sandro Keller was never mentioned in the Anwesenheit table at all -> roster
    # default of "absent", not silently dropped.
    assert entries_by_id[participants["Sandro Keller"].id]["status"] == "absent"

    new_participant = db.execute(
        select(Participant).where(Participant.tenant_id == tenant.id, Participant.display_name == "Ganz Neue Person")
    ).scalar_one()
    assert entries_by_id[new_participant.id]["status"] == "present"
    assert new_participant.joined_at == date(2026, 10, 18)

    # --- Termine -----------------------------------------------------------------
    herbsthock = db.get(Event, ctx["events"]["Herbsthock"].id)
    assert herbsthock.event_date == date(2026, 10, 18)  # unchanged, exact match
    vorstandssitzung = db.get(Event, ctx["events"]["Vorstandssitzung"].id)
    assert vorstandssitzung.event_date == date(2026, 10, 25)  # updated from 20.10 -> 25.10
    halloween = db.execute(
        select(Event).where(Event.tenant_id == tenant.id, Event.title == "Halloween-Party")
    ).scalar_one()
    assert halloween.event_date == date(2026, 11, 1)

    # --- Ämtli (list, snapshot-only) ----------------------------------------------
    amtli_block = _block_by_section(db, protocol_id, "Ämtli")
    snapshot_entries = amtli_block.configuration_snapshot_json["list_snapshot"]["entries"]
    by_col1 = {e["column_one_value"].get("text_value"): e for e in snapshot_entries}
    assert by_col1["Feuer"]["column_two_value"]["participant_id"] == participants["Timo Weber"].id
    assert by_col1["Fahrer"]["column_two_value"]["participant_id"] == participants["Sandro Keller"].id
    # The live ListEntry must NEVER be mutated by an import - lists are snapshot-only.
    live_feuer = db.get(ListEntry, ctx["existing_feuer_entry"].id)
    assert live_feuer.column_two_value_json["participant_id"] == participants["Nevio Muster"].id

    # --- Scharanlässe (form block) -------------------------------------------------
    scharanlaesse_block = _block_by_section(db, protocol_id, "Scharanlässe")
    rows_by_id = {r["id"]: r for r in scharanlaesse_block.configuration_snapshot_json["rows"]}
    assert rows_by_id["r_treff"]["text_value"] == "Vor der Kirche"
    assert rows_by_id["r_org"]["participant_id"] == participants["Timo Weber"].id
    assert set(rows_by_id["r_wer"]["participant_ids"]) == {participants["Timo Weber"].id, new_participant.id}

    # --- Rückblick (event-repeat text block) ---------------------------------------
    rueckblick_element = db.execute(
        select(ProtocolElement).where(
            ProtocolElement.protocol_id == protocol_id,
            ProtocolElement.section_name_snapshot == "Rückblick",
        )
    ).scalars().one()
    # create_from_template pre-creates one event-repeat block per event inside its
    # default forward window (event_window_end_days=14, since our fixture template
    # doesn't override it) - both Herbsthock and Vorstandssitzung fall in that window
    # at protocol-creation time, so two blocks legitimately exist under this element.
    # Only the Herbsthock one should carry the imported Rückblick text.
    rueckblick_blocks = list(
        db.execute(
            select(ProtocolElementBlock).where(ProtocolElementBlock.protocol_element_id == rueckblick_element.id)
        ).scalars()
    )
    assert len(rueckblick_blocks) == 2
    rueckblick_block = next(
        block for block in rueckblick_blocks
        if block.configuration_snapshot_json.get("repeat_source_id") == herbsthock.id
    )
    other_block = next(block for block in rueckblick_blocks if block.id != rueckblick_block.id)
    protocol_text = db.execute(
        select(ProtocolText).where(ProtocolText.protocol_element_block_id == rueckblick_block.id)
    ).scalar_one()
    assert "Gutes Wetter" in protocol_text.content
    other_text = db.execute(
        select(ProtocolText).where(ProtocolText.protocol_element_block_id == other_block.id)
    ).scalar_one_or_none()
    # The Vorstandssitzung Rückblick instance was never mentioned in the document -
    # its own ProtocolText (if any) must stay untouched, not accidentally receive the
    # Herbsthock text.
    if other_text is not None:
        assert "Gutes Wetter" not in other_text.content

    # --- Matrix ----------------------------------------------------------------
    matrix_block = _block_by_section(db, protocol_id, "Anwesenheitsmatrix")
    columns_by_title = {c["title"]: c for c in matrix_block.configuration_snapshot_json["columns"]}
    assert columns_by_title["18.10.2026"]["row_values"]["row1"]["participant_ids"] == [participants["Timo Weber"].id]
    assert set(columns_by_title["25.10.2026"]["row_values"]["row1"]["participant_ids"]) == {
        participants["Nevio Muster"].id, participants["Sandro Keller"].id,
    }

    # --- Profile learning ------------------------------------------------------
    profile = db.execute(
        select(WordImportProfile).where(WordImportProfile.tenant_id == tenant.id, WordImportProfile.template_id == ctx["template"].id)
    ).scalar_one()
    assert "ganz neue person" in profile.mapping_config_json["participant_name_overrides"]


def test_full_docx_import_lands_every_kind_of_data_correctly(db):
    spec = default_spec()
    raw_bytes = render_docx(spec)
    ctx, _payload, protocol_id = _run_full_import(db, raw_bytes)
    _assert_full_import(db, ctx, protocol_id)


def test_full_pdf_import_matches_docx_result(db):
    spec = default_spec()
    raw_bytes = render_pdf(spec)
    ctx, _payload, protocol_id = _run_full_import(db, raw_bytes)
    _assert_full_import(db, ctx, protocol_id)


def test_parse_document_dispatches_by_content_not_filename():
    """parse_document sniffs the real file signature - a .docx's bytes must never be
    mistaken for a PDF (and vice versa) no matter what a caller names the file."""
    spec = default_spec()
    docx_bytes = render_docx(spec)
    pdf_bytes = render_pdf(spec)
    assert parse_document(docx_bytes).tables
    assert parse_document(pdf_bytes).tables
    with pytest.raises(Exception):
        parse_document(b"not a real document")
