"""Nebenläufigkeit: Vorlage archivieren, während jemand sie als Standard zuweist.

Archivierte Vorlagen sind nirgends mehr Standard: ``set_archived`` entfernt ihre Zuweisungen.
``set_assignment`` prüfte «aktiv und veröffentlicht» aber am ungesperrten Stand, und das
Archivieren sah eine gleichzeitig angelegte, noch nicht festgeschriebene Zuweisung nicht. Danach
war die archivierte Vorlage Standard (Einstellungen zeigen sie, Dokumente fallen still auf die
Vorgabe zurück). Typisch: «Unbenutzte archivieren» im Aufräum-Dialog, während jemand anderes die
Vorlage gerade als Standard wählt. Erwartet: keine Zuweisung auf eine archivierte Vorlage.

Wie ``test_document_studio_race.py`` ohne ``db``-Fixture (echte, festgeschriebene Transaktionen).
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.db import engine
from app.documents import template_service
from app.documents.layout import TemplateContent
from app.models import DocumentTemplate, DocumentTemplateAssignment
from tests.factories import make_tenant

SIMPLE = {"masters": [{"id": "default"}], "body": [{"type": "text", "id": "t", "content": {"default": [{"t": "text", "v": "Stand"}]}}]}


def _session() -> Session:
    return Session(bind=engine.connect(), autoflush=False, future=True)


def _close(session: Session) -> None:
    connection = session.connection()
    session.close()
    connection.close()


@pytest.fixture
def ids():
    session = _session()
    try:
        tenant = make_tenant(session, "Archivieren parallel")
        template, _revision = template_service.create_template(session, tenant.id, name="Alt", document_type="protocol", content=TemplateContent.model_validate(SIMPLE))
        template_service.publish(session, template, user_id=None)
        session.commit()
        values = (tenant.id, template.id)
    finally:
        _close(session)
    yield values
    with engine.connect() as connection:
        connection.execute(text("DELETE FROM tenant WHERE id = :tid"), {"tid": values[0]})
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


def _assigned_archived(tenant_id: int) -> int:
    with Session(engine) as check:
        return check.scalar(
            select(func.count(DocumentTemplateAssignment.id))
            .join(DocumentTemplate, DocumentTemplate.id == DocumentTemplateAssignment.document_template_id)
            .where(DocumentTemplateAssignment.tenant_id == tenant_id, DocumentTemplate.status == "archived")
        )


def test_archive_while_assignment_is_pending_leaves_no_archived_default(ids):
    tenant_id, template_id = ids

    def archive_in_other_request() -> None:
        session = _session()
        try:
            template_service.set_archived(session, session.get(DocumentTemplate, template_id), True, user_id=None)
            session.commit()
        finally:
            _close(session)

    assigner = _session()
    try:
        template_service.set_assignment(assigner, tenant_id, document_type="protocol", template=assigner.get(DocumentTemplate, template_id), brand=None)
        with ThreadPoolExecutor(1) as pool:
            archived = pool.submit(archive_in_other_request)
            _wait_until_blocked(3.0)  # ohne Sperre läuft das Archivieren sofort durch
            assigner.commit()
            archived.result(timeout=15)
    finally:
        _close(assigner)
    assert _assigned_archived(tenant_id) == 0


def test_assignment_after_concurrent_archive_is_refused(ids):
    tenant_id, template_id = ids
    assigner = _session()
    try:
        template = assigner.get(DocumentTemplate, template_id)  # Stand vor dem Archivieren
        archiver = _session()
        try:
            template_service.set_archived(archiver, archiver.get(DocumentTemplate, template_id), True, user_id=None)
            archiver.commit()
        finally:
            _close(archiver)
        with pytest.raises(template_service.TemplateStateError):
            template_service.set_assignment(assigner, tenant_id, document_type="protocol", template=template, brand=None)
        assigner.rollback()
    finally:
        _close(assigner)
    assert _assigned_archived(tenant_id) == 0
