"""Further Word-Import E2E coverage beyond the "happy path" in test_word_import_e2e.py:
ZIP-batch upload extraction, umlaut/nickname name matching, German long-form dates,
an empty attendance table, and a list import that needs the "explode" row-grouping
strategy end to end (the grouping logic itself is already unit-tested in
test_word_import_service.py - this only checks the real DB round-trip lands it right).
"""
import io
import zipfile
from datetime import date

from app.schemas.word_import import WordImportCommit, WordImportListRowCommit
from app.services.file_service import extract_word_import_files_from_zip
from app.services.word_import_service import WordImportService, parse_document

from tests.factories import make_list_definition, make_list_entry, make_participant, make_protocol, make_template, make_tenant
from tests.word_import_fixtures import ProtocolSpec, TableSpec, TextSpec, default_spec, render_docx


def _zip_of(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def test_zip_extraction_keeps_only_real_docx_pdf_and_skips_junk():
    docx_a = render_docx(default_spec(date(2026, 10, 18)))
    docx_b = render_docx(default_spec(date(2026, 11, 15)))
    zip_bytes = _zip_of(
        {
            "protokoll_1.docx": docx_a,
            "subfolder/protokoll_2.docx": docx_b,
            "notizen.txt": b"kein Word-Import-Format",
            "__MACOSX/._protokoll_1.docx": b"junk",
            ".DS_Store": b"junk",
        }
    )

    matched, notes = extract_word_import_files_from_zip(zip_bytes)

    matched_names = {name for name, _content in matched}
    assert matched_names == {"protokoll_1.docx", "protokoll_2.docx"}
    assert any("notizen.txt" not in matched_names for _ in [0])


def test_zip_batch_documents_each_analyze_independently(db):
    """Mirrors what WordImportQueueService.ingest() does per extracted file (minus the
    disk/ClamAV storage step, which we don't want to touch from a test) - each entry of
    a multi-document ZIP batch must analyze correctly and independently of the others."""
    tenant = make_tenant(db)
    template = make_template(db, tenant.id, name="Hock-Protokoll")
    template.protocol_number_pattern = "P-{n}"
    db.flush()

    docx_a = render_docx(default_spec(date(2026, 10, 18)))
    docx_b = render_docx(default_spec(date(2026, 11, 15)))
    zip_bytes = _zip_of({"a.docx": docx_a, "b.docx": docx_b, "ignore.txt": b"x"})
    matched, notes = extract_word_import_files_from_zip(zip_bytes)
    assert len(matched) == 2
    assert notes == []

    service = WordImportService()
    analyses = [
        service.analyze(db, tenant_id=tenant.id, template_id=template.id, protocol_date_hint=None, raw_bytes=content)
        for _name, content in matched
    ]
    protocol_dates = {a.protocol_date for a in analyses}
    assert protocol_dates == {date(2026, 10, 18), date(2026, 11, 15)}


def test_umlaut_and_case_insensitive_name_matching(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id, name="Hock-Protokoll")
    template.protocol_number_pattern = "P-{n}"
    db.flush()
    participant = make_participant(db, tenant.id, "Jürgen Müller")
    from tests.factories import make_template_participant

    make_template_participant(db, template.id, participant.id)

    spec = ProtocolSpec(
        title="Protokoll vom 05.03.2026",
        attendance=TableSpec(
            heading="Anwesenheit", header_cells=["Name", "Status"],
            # No umlauts in the document at all (common when a document was typed on a
            # layout without German diacritics) - must still resolve via _fold_umlauts.
            rows=[["Juergen Muller", ""]],
        ),
        events=TableSpec(heading="Termine", header_cells=["Datum", "Anlass"], rows=[]),
        list_table=TableSpec(heading="Ämtli", header_cells=["Amt", "Person"], rows=[]),
        matrix=TableSpec(heading="Matrix", header_cells=[], rows=[]),
        form_text=TextSpec(heading="Scharanlässe", lines=[]),
        rueckblick_text=TextSpec(heading="Sonstiges", lines=["Nichts Besonderes."]),
    )
    raw_bytes = render_docx(spec)
    analysis = WordImportService().analyze(
        db, tenant_id=tenant.id, template_id=template.id, protocol_date_hint=None, raw_bytes=raw_bytes
    )
    mapping = next(m for m in analysis.attendance_mappings if m.raw_name == "Juergen Muller")
    assert mapping.suggested_participant_id == participant.id


def test_german_long_form_date_is_parsed_as_protocol_date(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id, name="Hock-Protokoll")
    template.protocol_number_pattern = "P-{n}"
    db.flush()

    spec = ProtocolSpec(
        title="Protokoll vom 14. Mai 2026",
        attendance=TableSpec(heading="Anwesenheit", header_cells=["Name", "Status"], rows=[]),
        events=TableSpec(heading="Termine", header_cells=["Datum", "Anlass"], rows=[]),
        list_table=TableSpec(heading="Ämtli", header_cells=["Amt", "Person"], rows=[]),
        matrix=TableSpec(heading="Matrix", header_cells=[], rows=[]),
        form_text=TextSpec(heading="Scharanlässe", lines=[]),
        rueckblick_text=TextSpec(heading="Sonstiges", lines=["Nichts Besonderes."]),
    )
    raw_bytes = render_docx(spec)
    analysis = WordImportService().analyze(
        db, tenant_id=tenant.id, template_id=template.id, protocol_date_hint=None, raw_bytes=raw_bytes
    )
    assert analysis.protocol_date == date(2026, 5, 14)


def test_analyze_flags_an_existing_protocol_for_the_same_template_and_date(db):
    """Real bug fixed here: the standalone /tools/word-import wizard never creates a
    WordImportDocument (see commit_word_import), so it was completely blind to the
    queue's own duplicate hint (which only compares WordImportDocument rows) - the same
    old protocol could be imported twice with zero warning. analyze() now checks the
    Protocol table directly instead."""
    tenant = make_tenant(db)
    template = make_template(db, tenant.id, name="Hock-Protokoll")
    template.protocol_number_pattern = "P-{n}"
    db.flush()
    existing = make_protocol(db, tenant.id, template.id, protocol_number="P-1", protocol_date=date(2026, 3, 5))

    spec = default_spec(date(2026, 3, 5))
    raw_bytes = render_docx(spec)
    analysis = WordImportService().analyze(
        db, tenant_id=tenant.id, template_id=template.id, protocol_date_hint=None, raw_bytes=raw_bytes
    )

    assert [duplicate.id for duplicate in analysis.duplicate_protocols] == [existing.id]


def test_analyze_does_not_flag_a_protocol_on_a_different_date_or_template(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id, name="Hock-Protokoll")
    template.protocol_number_pattern = "P-{n}"
    other_template = make_template(db, tenant.id, name="Anderes Protokoll")
    other_template.protocol_number_pattern = "Q-{n}"
    db.flush()
    make_protocol(db, tenant.id, template.id, protocol_number="P-1", protocol_date=date(2026, 4, 1))
    make_protocol(db, tenant.id, other_template.id, protocol_number="Q-1", protocol_date=date(2026, 3, 5))

    spec = default_spec(date(2026, 3, 5))
    raw_bytes = render_docx(spec)
    analysis = WordImportService().analyze(
        db, tenant_id=tenant.id, template_id=template.id, protocol_date_hint=None, raw_bytes=raw_bytes
    )

    assert analysis.duplicate_protocols == []


def test_empty_attendance_table_still_defaults_whole_roster_to_absent(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id, name="Hock-Protokoll")
    template.protocol_number_pattern = "P-{n}"
    db.flush()
    participant = make_participant(db, tenant.id, "Timo Weber")
    from tests.factories import make_template_participant

    make_template_participant(db, template.id, participant.id)

    spec = ProtocolSpec(
        title="Protokoll vom 05.03.2026",
        attendance=TableSpec(heading="Anwesenheit", header_cells=["Name", "Status"], rows=[]),
        events=TableSpec(heading="Termine", header_cells=["Datum", "Anlass"], rows=[]),
        list_table=TableSpec(heading="Ämtli", header_cells=["Amt", "Person"], rows=[]),
        matrix=TableSpec(heading="Matrix", header_cells=[], rows=[]),
        form_text=TextSpec(heading="Scharanlässe", lines=[]),
        rueckblick_text=TextSpec(heading="Sonstiges", lines=["Nichts Besonderes."]),
    )
    raw_bytes = render_docx(spec)
    analysis = WordImportService().analyze(
        db, tenant_id=tenant.id, template_id=template.id, protocol_date_hint=None, raw_bytes=raw_bytes
    )
    assert len(analysis.attendance_mappings) == 1
    only_mapping = analysis.attendance_mappings[0]
    assert only_mapping.raw_name == ""
    assert only_mapping.status == "absent"
    assert only_mapping.suggested_participant_id == participant.id


def test_list_explode_grouping_round_trips_through_real_commit(db):
    """E2E companion to the pure-logic unit tests in test_word_import_service.py - a
    document row like "Enea | Omlin & Partner Gmbh, Felsenheim" must still explode into
    the right per-person snapshot rows after a REAL analyze()+commit() round trip, not
    just inside the private helper functions."""
    from app.models import ElementType, RenderType
    from sqlalchemy import select

    from tests.factories import make_element_definition, make_template_element, make_template_participant

    tenant = make_tenant(db)
    template = make_template(db, tenant.id, name="Hock-Protokoll")
    template.protocol_number_pattern = "P-{n}"
    db.flush()
    enea = make_participant(db, tenant.id, "Enea")
    lauri = make_participant(db, tenant.id, "Lauri")
    for p in (enea, lauri):
        make_template_participant(db, template.id, p.id)

    sponsoring = make_list_definition(
        db, tenant.id, name="Sponsoring",
        column_one_title="Sponsor", column_one_value_type="text",
        column_two_title="Verantwortlich", column_two_value_type="participant",
    )
    make_list_entry(db, sponsoring.id, sort_index=0, column_one_value={"text_value": "Omlin & Partner Gmbh"}, column_two_value={"participant_id": enea.id})
    make_list_entry(db, sponsoring.id, sort_index=1, column_one_value={"text_value": "Felsenheim"}, column_two_value={"participant_id": enea.id})
    make_list_entry(db, sponsoring.id, sort_index=2, column_one_value={"text_value": "Dolomiten Sport"}, column_two_value={"participant_id": enea.id})
    make_list_entry(db, sponsoring.id, sort_index=3, column_one_value={"text_value": "Raiffeisen"}, column_two_value={"participant_id": lauri.id})

    form_type = db.scalar(select(ElementType.id).where(ElementType.code == "form"))
    render_type = db.scalar(select(RenderType.id).where(RenderType.code == "key_value"))
    definition = make_element_definition(
        db, tenant.id, "Sponsoring",
        blocks=[{
            "id": 1, "title": "Sponsoring", "description": None, "block_title": None,
            "default_content": "", "copy_from_last_protocol": False,
            "element_type_id": form_type, "render_type_id": render_type,
            "is_editable": True, "allows_multiple_values": False, "export_visible": True, "is_visible": True,
            "sort_index": 10, "render_order": 10, "latex_template": None,
            "configuration_json": {"linked_list_id": sponsoring.id, "rows": []},
        }],
    )
    make_template_element(db, template.id, definition.id, sort_index=10, section_name="Sponsoring")

    spec = ProtocolSpec(
        title="Protokoll vom 05.03.2026",
        attendance=TableSpec(heading="Anwesenheit", header_cells=["Name", "Status"], rows=[]),
        events=TableSpec(heading="Termine", header_cells=["Datum", "Anlass"], rows=[]),
        list_table=TableSpec(
            heading="Sponsoring", header_cells=["Verantwortlich", "Sponsor"],
            rows=[["Enea", "Omlin & Partner Gmbh, Felsenheim, Dolomiten Sport"], ["Lauri", "Raiffeisen"]],
        ),
        matrix=TableSpec(heading="Matrix", header_cells=[], rows=[]),
        form_text=TextSpec(heading="Scharanlässe", lines=[]),
        rueckblick_text=TextSpec(heading="Sonstiges", lines=["Nichts Besonderes."]),
    )
    raw_bytes = render_docx(spec)
    service = WordImportService()
    analysis = service.analyze(db, tenant_id=tenant.id, template_id=template.id, protocol_date_hint=None, raw_bytes=raw_bytes)

    table = next(t for t in analysis.tables if t.header_cells == ["Verantwortlich", "Sponsor"])
    assert table.role == "list"
    assert table.grouping_strategy == "explode_swap:comma"
    assert not table.needs_manual_grouping

    lists = [
        WordImportListRowCommit(
            table_index=mapping.table_index,
            list_definition_id=sponsoring.id,
            column_one_raw=mapping.column_one_raw,
            column_two_raw=mapping.column_two_raw,
            column_one_names=mapping.column_one_names,
            column_two_names=mapping.column_two_names,
            approved=True,
            linked_entry_id=mapping.matched_entry_id,
        )
        for mapping in analysis.list_mappings
    ]
    payload = WordImportCommit(template_id=template.id, protocol_date=analysis.protocol_date, lists=lists)
    protocol_id = service.commit(db, tenant_id=tenant.id, user_id=1, payload=payload).id

    from app.models import ProtocolElement, ProtocolElementBlock

    block = db.execute(
        select(ProtocolElementBlock)
        .join(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
        .where(ProtocolElement.protocol_id == protocol_id, ProtocolElement.section_name_snapshot == "Sponsoring")
    ).scalars().one()
    entries = block.configuration_snapshot_json["list_snapshot"]["entries"]
    by_sponsor = {e["column_one_value"].get("text_value"): e["column_two_value"].get("participant_id") for e in entries}
    assert by_sponsor["Omlin & Partner Gmbh"] == enea.id
    assert by_sponsor["Felsenheim"] == enea.id
    assert by_sponsor["Dolomiten Sport"] == enea.id
    assert by_sponsor["Raiffeisen"] == lauri.id
