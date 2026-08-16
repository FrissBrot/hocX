"""Regression tests for NIEDRIG findings from the 2026-08-16 audit."""
from datetime import date

import pytest
from fastapi import HTTPException

from tests.factories import make_current_user, make_participant, make_protocol, make_tenant, make_template


# --- S11: scroll-position endpoints now tenant-scoped -------------------------------------


def test_get_element_position_rejects_foreign_tenant_protocol(db):
    from app.api.routes import protocols as protocols_route

    tenant_a = make_tenant(db, "Tenant A (S11)")
    tenant_b = make_tenant(db, "Tenant B (S11)")
    template_b = make_template(db, tenant_b.id)
    protocol_b = make_protocol(db, tenant_b.id, template_b.id)
    user_a = make_current_user(tenant_a.id, role="writer")

    with pytest.raises(HTTPException) as exc_info:
        protocols_route.get_element_position(protocol_b.id, db=db, user=user_a)
    assert exc_info.value.status_code == 404


def test_save_element_position_rejects_foreign_tenant_protocol(db):
    from app.api.routes import protocols as protocols_route

    tenant_a = make_tenant(db, "Tenant A (S11b)")
    tenant_b = make_tenant(db, "Tenant B (S11b)")
    template_b = make_template(db, tenant_b.id)
    protocol_b = make_protocol(db, tenant_b.id, template_b.id)
    user_a = make_current_user(tenant_a.id, role="writer")

    with pytest.raises(HTTPException) as exc_info:
        protocols_route.save_element_position(
            protocol_b.id, protocols_route.ElementPositionPayload(element_id=1), db=db, user=user_a
        )
    assert exc_info.value.status_code == 404


# --- D7: participant_service is now tenant-scoped directly --------------------------------


def test_get_participant_returns_none_for_foreign_tenant(db):
    from app.services.participant_service import ParticipantService

    tenant_a = make_tenant(db, "Tenant A (D7)")
    tenant_b = make_tenant(db, "Tenant B (D7)")
    participant_b = make_participant(db, tenant_b.id, "Foreign Participant")

    service = ParticipantService()
    assert service.get_participant(db, participant_b.id, tenant_id=tenant_a.id) is None
    assert service.get_participant(db, participant_b.id, tenant_id=tenant_b.id) is not None


def test_delete_participant_returns_false_for_foreign_tenant(db):
    from app.services.participant_service import ParticipantService

    tenant_a = make_tenant(db, "Tenant A (D7b)")
    tenant_b = make_tenant(db, "Tenant B (D7b)")
    participant_b = make_participant(db, tenant_b.id, "Foreign Participant (D7b)")

    service = ParticipantService()
    assert service.delete_participant(db, participant_b.id, tenant_id=tenant_a.id) is False


# --- D13: word-import queue display names recomputed once the whole batch is committed ----


def test_compute_display_name_sees_a_later_committed_batch_sibling(db):
    # Lower-level than driving ingest() through the full docx pipeline (whose extraction
    # quirks aren't what D13 is about): seeds two "eingelesen" WordImportDocument rows
    # directly, exactly the state ingest()'s second pass (audit D13, 2026-08-16) now runs
    # against, and checks _compute_display_name picks up the sibling that was committed
    # after the one being previewed.
    from app.models import StoredFile, WordImportDocument
    from app.services.word_import_queue_service import WordImportQueueService

    tenant = make_tenant(db, "Tenant (D13)")
    template = make_template(db, tenant.id)
    template.title_pattern = "{n}. Hock"
    db.flush()

    def _seed_document(filename: str, protocol_date: date) -> WordImportDocument:
        stored_file = StoredFile(
            tenant_id=tenant.id, storage_path=f"word-imports/{filename}", original_name=filename,
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            file_size_bytes=1, scan_status="clean",
        )
        db.add(stored_file)
        db.flush()
        document = WordImportDocument(
            tenant_id=tenant.id, template_id=template.id, stored_file_id=stored_file.id,
            original_filename=filename, display_name=filename, protocol_date=protocol_date,
            status="eingelesen", analysis_snapshot_json={},
        )
        db.add(document)
        db.flush()
        return document

    # march.docx ingested first, before january.docx (its earlier-dated batch sibling)
    # existed as a row yet.
    march = _seed_document("march.docx", date(2026, 3, 1))
    _seed_document("january.docx", date(2026, 1, 1))

    queue_service = WordImportQueueService()
    recomputed = queue_service._compute_display_name(
        db, tenant_id=tenant.id, template_id=template.id, protocol_date=march.protocol_date,
        fallback="march.docx", exclude_document_id=march.id,
    )
    # Rank 2 (january.docx ranks 1st) - before the D13 fix, a caller that only knew about
    # already-committed-BEFORE-it siblings would have seen none and wrongly computed "1.".
    assert "2." in recomputed
