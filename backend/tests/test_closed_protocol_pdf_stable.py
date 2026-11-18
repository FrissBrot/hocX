"""PDF nur bei Änderung: Abgeschlossene Protokolle liefern immer dasselbe finale PDF (gleiche
Dokument-ID, gleicher Prüf-Hash), bis das Protokoll zurückgestuft und erneut abgeschlossen wird.
Offene Protokolle liefern das letzte PDF, solange Inhalt und Gestaltung unverändert sind."""
from __future__ import annotations

import hashlib
import secrets
from datetime import date
from types import SimpleNamespace

import pytest

from app.core.storage import MAIN, get_object_store
from app.documents.service import FULL_VIEW, DocumentRequest, _reuse_closed_export, _reuse_existing_export, document_view_key
from app.models import DocumentExport, DocumentRegistry, StoredFile
from app.schemas.protocol import ProtocolUpdate
from app.services.protocol_service import ProtocolService
from tests.factories import make_protocol, make_template, make_tenant


@pytest.fixture(autouse=True)
def _isolated_storage(monkeypatch, tmp_path):
    from app.core.config import settings

    monkeypatch.setattr(settings, "storage_root", str(tmp_path / "storage"))


def _pdf(
    db, protocol, status: str, *, language: str = "de", options: dict | None = None, content: str = "inhalt", design: str = "design", view: str = FULL_VIEW
) -> DocumentExport:
    data = secrets.token_bytes(32)
    key = f"exports/generated/{secrets.token_hex(6)}.pdf"
    get_object_store().put_bytes(db, MAIN, key, data, content_type="application/pdf")
    stored = StoredFile(tenant_id=protocol.tenant_id, original_name="p.pdf", mime_type="application/pdf", storage_path=key, scan_status="clean")
    db.add(stored)
    db.flush()
    export = DocumentExport(
        tenant_id=protocol.tenant_id, protocol_id=protocol.id, document_type="protocol", title=protocol.title,
        stored_file_id=stored.id, language=language, content_hash=content, design_hash=design,
        options_json={"options": options or DocumentRequest().options.model_dump(mode="json"), "view": view},
    )
    db.add(export)
    db.flush()
    db.add(DocumentRegistry(public_id=export.public_id, tenant_id=protocol.tenant_id, sha256=hashlib.sha256(data).hexdigest(),
                            document_type="protocol", title=protocol.title, status_code=status, source_public_id=protocol.public_id))
    db.flush()
    return export


def _prepared(protocol, *, language: str = "de", title_overridden: bool = False, content: str = "inhalt", design: str = "design"):
    return SimpleNamespace(
        protocol=protocol, document_type="protocol", title_overridden=title_overridden, template=None, language=language,
        content_hash=content, design_hash=design, version=(0, 0, 0),
    )


def _protocol(db, name: str):
    tenant = make_tenant(db, name)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, protocol_number="S-1", protocol_date=date(2026, 3, 1), status="durchgeführt")
    protocol.title = "Sitzung"
    db.flush()
    return protocol


def test_opening_a_closed_protocol_returns_the_existing_final_pdf(db):
    protocol = _protocol(db, "Stabil")
    ProtocolService().update_protocol(db, protocol.id, ProtocolUpdate(status="abgeschlossen"))
    final = _pdf(db, protocol, "abgeschlossen")
    request = DocumentRequest(protocol_id=protocol.public_id, document_type="protocol")

    # Gleiches Dokument, auch wenn die Person eine andere UI-Sprache hat
    for language in ("de", "fr"):
        reused = _reuse_closed_export(db, request, _prepared(protocol, language=language), FULL_VIEW)
        assert reused is not None and reused.export.public_id == final.public_id


def test_explicit_variants_and_open_protocols_render_new(db):
    protocol = _protocol(db, "Varianten")
    request = DocumentRequest(protocol_id=protocol.public_id, document_type="protocol")
    _pdf(db, protocol, "durchgeführt")
    # Noch nicht abgeschlossen: jedes Öffnen zeigt den aktuellen Stand
    assert _reuse_closed_export(db, request, _prepared(protocol), FULL_VIEW) is None

    ProtocolService().update_protocol(db, protocol.id, ProtocolUpdate(status="abgeschlossen"))
    _pdf(db, protocol, "abgeschlossen")
    assert _reuse_closed_export(db, request.model_copy(update={"language": "fr"}), _prepared(protocol, language="fr"), FULL_VIEW) is None
    assert _reuse_closed_export(db, request, _prepared(protocol, title_overridden=True), FULL_VIEW) is None


def test_reclosing_after_a_downgrade_creates_a_new_final_pdf(db):
    protocol = _protocol(db, "Korrektur")
    service = ProtocolService()
    request = DocumentRequest(protocol_id=protocol.public_id, document_type="protocol")
    service.update_protocol(db, protocol.id, ProtocolUpdate(status="abgeschlossen"))
    _pdf(db, protocol, "abgeschlossen")
    service.update_protocol(db, protocol.id, ProtocolUpdate(status="durchgeführt"))
    service.update_protocol(db, protocol.id, ProtocolUpdate(status="abgeschlossen"))
    # Das PDF des früheren Abschlusses ist ersetzt: neues Rendern nötig
    assert _reuse_closed_export(db, request, _prepared(protocol), FULL_VIEW) is None


def test_unchanged_draft_returns_the_latest_pdf_and_any_change_renders_new(db):
    protocol = _protocol(db, "Entwurf")
    request = DocumentRequest(protocol_id=protocol.public_id, document_type="protocol")
    latest = _pdf(db, protocol, "durchgeführt")

    reused = _reuse_existing_export(db, request, _prepared(protocol), None, FULL_VIEW)
    assert reused is not None and reused.export.public_id == latest.public_id
    # Geänderter Inhalt, geänderte Gestaltung oder andere Sprache: neues PDF
    assert _reuse_existing_export(db, request, _prepared(protocol, content="neu"), None, FULL_VIEW) is None
    assert _reuse_existing_export(db, request, _prepared(protocol, design="neu"), None, FULL_VIEW) is None
    assert _reuse_existing_export(db, request, _prepared(protocol, language="fr"), None, FULL_VIEW) is None
    # Andere Prüf-Domain ebenso; dieselbe Prüfseite mit anderer Dokument-ID nicht
    assert _reuse_existing_export(db, request, _prepared(protocol), "https://verify.example.org?id=x", FULL_VIEW) is None
    latest.options_json = {**latest.options_json, "verify_url": "https://verify.example.org?id=alt"}
    db.flush()
    assert _reuse_existing_export(db, request, _prepared(protocol), "https://verify.example.org?id=neu", FULL_VIEW).export.public_id == latest.public_id


def test_status_change_renders_new_even_with_the_same_content(db):
    protocol = _protocol(db, "Statuswechsel")
    request = DocumentRequest(protocol_id=protocol.public_id, document_type="protocol")
    _pdf(db, protocol, "vorbereitet")
    assert _reuse_existing_export(db, request, _prepared(protocol), None, FULL_VIEW) is None


def test_a_restricted_view_never_gets_the_shared_pdf(db):
    protocol = _protocol(db, "Sichten")
    ProtocolService().update_protocol(db, protocol.id, ProtocolUpdate(status="abgeschlossen"))
    final = _pdf(db, protocol, "abgeschlossen")  # z. B. Auto-PDF beim Abschliessen (ohne Person)
    request = DocumentRequest(protocol_id=protocol.public_id, document_type="protocol")

    assert _reuse_closed_export(db, request, _prepared(protocol), "user:42") is None
    own = _pdf(db, protocol, "abgeschlossen", view="user:42")
    assert _reuse_closed_export(db, request, _prepared(protocol), "user:42").export.public_id == own.public_id
    # Das gemeinsame PDF bleibt für die uneingeschränkte Sicht dasselbe
    assert _reuse_closed_export(db, request, _prepared(protocol), FULL_VIEW).export.public_id == final.public_id


def test_view_key_without_person_is_the_full_view(db):
    assert document_view_key(db, None) == FULL_VIEW
