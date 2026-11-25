"""Protokoll-PDF je Sicht (document_view_key): Wer Bussen anderer Personen bzw. Finanzen nicht sehen
darf, bekommt ein eigenes, eingeschränktes PDF - nie das gemeinsame («full», z. B. das Auto-PDF beim
Abschliessen mit allen Bussen). Die Protokollliste (latest_pdf_url), die Exportliste und der
Datei-Download dürfen dieses PDF an eine eingeschränkte Person deshalb nicht herausgeben."""
from __future__ import annotations

import secrets
import uuid
from datetime import date

import pytest
from fastapi import HTTPException

from app.api.routes import documents as document_routes
from app.api.routes import protocols as protocol_routes
from app.core.storage import MAIN, get_object_store
from app.documents.service import FULL_VIEW, DocumentRequest
from app.models import DocumentExport, StoredFile
from app.services.access_service import AccessService
from tests.factories import make_current_user, make_participant, make_protocol, make_template, make_tenant, system_role_permissions


@pytest.fixture(autouse=True)
def _isolated_storage(monkeypatch, tmp_path):
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_root", str(tmp_path / "storage"))


def _pdf(db, protocol, view: str) -> StoredFile:
    key = f"exports/generated/{secrets.token_hex(6)}.pdf"
    get_object_store().put_bytes(db, MAIN, key, secrets.token_bytes(16), content_type="application/pdf")
    stored = StoredFile(tenant_id=protocol.tenant_id, original_name="p.pdf", mime_type="application/pdf", storage_path=key, scan_status="clean")
    db.add(stored)
    db.flush()
    db.add(DocumentExport(
        tenant_id=protocol.tenant_id, protocol_id=protocol.id, document_type="protocol", title="Sitzung",
        stored_file_id=stored.id, language="de", content_hash="c", design_hash="d",
        options_json={"options": DocumentRequest().options.model_dump(mode="json"), "view": view},
    ))
    db.flush()
    return stored


def _setup(db):
    tenant = make_tenant(db, "Verein PDF-Sicht")
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, protocol_number="S-1", protocol_date=date(2026, 3, 1), status="abgeschlossen")
    me = make_participant(db, tenant.id, "Lea Leserin")
    reader = make_current_user(tenant.id, role="reader", user_id=me.id, permissions=system_role_permissions("reader"))
    full = _pdf(db, protocol, FULL_VIEW)  # Auto-PDF beim Abschliessen: alle Bussen, Kontostand
    return protocol, reader, full


def test_protocol_list_does_not_hand_the_full_pdf_to_a_restricted_reader(db):
    protocol, reader, full = _setup(db)

    listed = protocol_routes.list_protocols(q=None, status_filter=None, skip=0, limit=100, db=db, user=reader)

    row = next(item for item in listed if item.id == protocol.public_id)
    assert row.latest_pdf_url != f"/api/stored-files/{full.public_id}/content"


def test_restricted_reader_cannot_download_the_full_protocol_pdf(db):
    protocol, reader, full = _setup(db)

    with pytest.raises(HTTPException) as excinfo:
        AccessService().ensure_can_read_stored_file(db, reader, full.id)
    assert excinfo.value.status_code == 404


def test_restricted_reader_reads_own_view_pdf(db):
    protocol, reader, _full = _setup(db)
    own = _pdf(db, protocol, f"user:{reader.user_id}")

    AccessService().ensure_can_read_stored_file(db, reader, own.id)
    listed = protocol_routes.list_protocols(q=None, status_filter=None, skip=0, limit=100, db=db, user=reader)
    row = next(item for item in listed if item.id == protocol.public_id)
    assert row.latest_pdf_url == f"/api/stored-files/{own.public_id}/content"


def test_export_list_hides_full_pdf_from_restricted_reader(db):
    protocol, reader, full = _setup(db)

    exports = document_routes.list_document_exports(
        protocol_id=protocol.public_id, document_type=None, limit=20, offset=0, db=db, user=reader,
    )
    assert all(item.generated_file_id != full.public_id for item in exports)


def test_unrestricted_user_still_gets_the_full_pdf(db):
    protocol, _reader, full = _setup(db)
    admin = make_current_user(protocol.tenant_id, role="admin", user_id=uuid.uuid4().int % 100000 + 100000)

    AccessService().ensure_can_read_stored_file(db, admin, full.id)
