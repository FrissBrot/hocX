"""Nebenläufigkeit: Brand-Profil löschen, während es gerade verwendet wird.

``delete_brand`` löscht nur unbenutzte Profile (Exporte, Vorlagen, Zuweisungen, festgehaltene
Revisionen) - sonst setzten die Fremdschlüssel Verweise still zurück. Die Zählung lief aber ohne
Sperre: Eine gleichzeitig gesetzte Standard-Zuweisung mit diesem Profil (noch nicht
festgeschrieben) war unsichtbar und wurde danach per ``ON DELETE CASCADE`` mitgelöscht; ein
gleichzeitig entstehender Export verlor seine ``brand_revision_id`` (``ON DELETE SET NULL``).
Erwartet: Das Löschen wartet und lehnt mit «Profil in Verwendung» ab.

Wie ``test_document_studio_race.py`` ohne ``db``-Fixture (echte, festgeschriebene Transaktionen).
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.db import engine
from app.documents import brand_service
from app.models import DocumentBrand, DocumentBrandRevision, DocumentTemplateAssignment
from app.models.entities import DocumentExport
from tests.factories import make_tenant


def _session() -> Session:
    return Session(bind=engine.connect(), autoflush=False, future=True)


def _close(session: Session) -> None:
    connection = session.connection()
    session.close()
    connection.close()


@pytest.fixture
def setup_ids():
    session = _session()
    try:
        tenant = make_tenant(session, "Brand löschen parallel")
        brand_service.create_brand(session, tenant.id, name="Standard", is_default=True)
        extra = brand_service.create_brand(session, tenant.id, name="Zusatz")
        session.commit()
        revision_id = session.scalar(select(DocumentBrandRevision.id).where(DocumentBrandRevision.brand_id == extra.id))
        ids = (tenant.id, extra.id, revision_id)
    finally:
        _close(session)
    yield ids
    with engine.connect() as connection:
        connection.execute(text("DELETE FROM tenant WHERE id = :tid"), {"tid": ids[0]})
        connection.commit()


def _wait_until_blocked(timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    with engine.connect() as probe:
        while time.monotonic() < deadline:
            waiting = probe.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock' AND datname = current_database()"))
            # pg_stat_activity ist je Transaktion ein fester Schnappschuss: jede Abfrage neu
            probe.rollback()
            if waiting:
                return True
            time.sleep(0.05)
    return False


def _delete_while_pending(brand_id: int, pending: Session) -> None:
    """``pending`` hat seinen Verweis geschrieben, aber nicht festgeschrieben; Löschen läuft in
    einer zweiten Verbindung, danach wird ``pending`` festgeschrieben."""

    def delete_in_other_request() -> None:
        session = _session()
        try:
            brand_service.delete_brand(session, session.get(DocumentBrand, brand_id))
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            _close(session)

    with ThreadPoolExecutor(1) as pool:
        deletion = pool.submit(delete_in_other_request)
        _wait_until_blocked(3.0)
        pending.commit()
        with pytest.raises(brand_service.BrandValidationError):
            deletion.result(timeout=15)


def test_delete_waits_for_assignment_with_the_brand(setup_ids):
    tenant_id, brand_id, _revision_id = setup_ids
    pending = _session()
    try:
        assignment = DocumentTemplateAssignment(tenant_id=tenant_id, document_type="protocol", brand_id=brand_id)
        pending.add(assignment)
        pending.flush()
        assignment_id = assignment.id
        _delete_while_pending(brand_id, pending)
    finally:
        _close(pending)
    with Session(engine) as check:
        assert check.get(DocumentBrand, brand_id) is not None
        assert check.get(DocumentTemplateAssignment, assignment_id) is not None


def test_delete_waits_for_export_with_the_brand(setup_ids):
    tenant_id, brand_id, revision_id = setup_ids
    pending = _session()
    try:
        export = DocumentExport(tenant_id=tenant_id, document_type="protocol", brand_revision_id=revision_id)
        pending.add(export)
        pending.flush()
        export_id = export.id
        _delete_while_pending(brand_id, pending)
    finally:
        _close(pending)
    with Session(engine) as check:
        assert check.get(DocumentBrand, brand_id) is not None
        assert check.get(DocumentExport, export_id).brand_revision_id == revision_id


def test_unused_brand_is_deleted_and_default_brand_is_refused(setup_ids):
    tenant_id, brand_id, _revision_id = setup_ids
    session = _session()
    try:
        brand_service.delete_brand(session, session.get(DocumentBrand, brand_id))
        session.commit()
        assert session.get(DocumentBrand, brand_id) is None
        default = brand_service.default_brand(session, tenant_id)
        with pytest.raises(brand_service.BrandValidationError):
            brand_service.delete_brand(session, default)
        session.rollback()
    finally:
        _close(session)
