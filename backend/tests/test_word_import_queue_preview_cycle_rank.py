"""Regression test: the Word-Import queue's preview display_name must account for other
still-open ("eingelesen", not yet committed) sibling documents of the same template, not just
already-committed Protocol rows.

Before this fix, WordImportQueueService._compute_display_name() called
ProtocolService.preview_title() with only real Protocol rows in scope. Since queued-but-
uncommitted documents aren't Protocol rows yet, uploading several historical documents together
in one batch (a normal Word-Import backfill workflow - see _BATCH_CONSENSUS_MIN_DOCS) made every
document in that batch preview with the identical number (e.g. all "1. Hock ...") until the
first one was actually committed - even though the documents' own protocol_dates put them in a
clear chronological order within the cycle. Fix: _compute_display_name() now also queries
sibling "eingelesen" WordImportDocument rows and feeds their protocol_dates into
preview_title()'s new extra_dates parameter (backend/app/services/protocol_service.py,
_add_virtual_dates / preview_title).
"""
from __future__ import annotations

from datetime import date

from app.models import StoredFile, WordImportDocument
from app.services.word_import_queue_service import WordImportQueueService

from tests.factories import make_tenant, make_template


def make_stored_file(db, tenant_id: int, name: str = "file.docx") -> StoredFile:
    row = StoredFile(tenant_id=tenant_id, original_name=name, storage_path=f"/tmp/{name}")
    db.add(row)
    db.flush()
    return row


def make_word_import_document(
    db, tenant_id: int, template_id: int, stored_file_id: int, *, protocol_date: date, status: str = "eingelesen"
) -> WordImportDocument:
    row = WordImportDocument(
        tenant_id=tenant_id,
        template_id=template_id,
        stored_file_id=stored_file_id,
        original_filename="import.docx",
        display_name="placeholder",
        protocol_date=protocol_date,
        status=status,
    )
    db.add(row)
    db.flush()
    return row


def test_batch_uploaded_siblings_still_queued_get_distinct_dateranked_previews(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    template.protocol_number_pattern = "P-{n}"
    template.title_pattern = "{n}. Hock vom {dd.mm.yyyy}"
    db.flush()
    stored_file = make_stored_file(db, tenant.id)

    # Two documents already sit in the queue, uncommitted (as if just ingested together in one
    # batch upload) - no real Protocol rows exist yet for either of them.
    make_word_import_document(db, tenant.id, template.id, stored_file.id, protocol_date=date(2025, 9, 1))
    make_word_import_document(db, tenant.id, template.id, stored_file.id, protocol_date=date(2025, 10, 14))

    queue_service = WordImportQueueService()
    # A third document, dated after both, is about to be previewed (e.g. the last file in the
    # same batch) - its preview must rank after both open siblings, not collide with "P-1".
    preview = queue_service._compute_display_name(
        db, tenant_id=tenant.id, template_id=template.id, protocol_date=date(2026, 2, 24), fallback="fallback.docx"
    )
    assert preview == "3. Hock vom 24.02.2026"


def test_reanalyzing_a_queued_document_does_not_count_itself(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    template.title_pattern = "{n}. Hock vom {dd.mm.yyyy}"
    db.flush()
    stored_file = make_stored_file(db, tenant.id)

    document = make_word_import_document(db, tenant.id, template.id, stored_file.id, protocol_date=date(2025, 10, 14))

    queue_service = WordImportQueueService()
    preview = queue_service._compute_display_name(
        db,
        tenant_id=tenant.id,
        template_id=template.id,
        protocol_date=document.protocol_date,
        fallback="fallback.docx",
        exclude_document_id=document.id,
    )
    # Without exclude_document_id, this document would count itself as its own predecessor and
    # incorrectly preview as "2." instead of "1.".
    assert preview == "1. Hock vom 14.10.2025"
