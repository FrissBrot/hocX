"""Nebenläufigkeit: Vorlage archivieren, während jemand sie als Standard zuweist (Issue #102).

Archivierte Vorlagen sind nirgends mehr Standard: ``set_archived`` entfernt ihre Zuweisungen.
``set_assignment`` prüfte «aktiv und veröffentlicht» aber am ungesperrten, evtl. veralteten Stand,
und das Archivieren sah eine gleichzeitig angelegte, noch nicht festgeschriebene Zuweisung nicht.
Danach war die archivierte Vorlage Standard (Einstellungen zeigen sie, Dokumente fallen still auf
die Vorgabe zurück). Typisch: «Unbenutzte archivieren» im Aufräum-Dialog, während jemand anderes
die Vorlage gerade als Standard wählt. Erwartet: keine Zuweisung auf eine archivierte Vorlage.

Systemvorlagen (``tenant_id IS NULL``) gehören dazu: der Plattform-Admin archiviert sie, Mandanten
weisen sie zu. Ein Mandant darf sie unter RLS lesen, aber nicht sperren (``FOR SHARE`` prüft die
Schreib-Policy) - die Zuweisung muss unter der Laufzeitrolle weiter funktionieren.

Wie ``test_document_studio_race.py`` ohne ``db``-Fixture (echte, festgeschriebene Transaktionen).
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.db import engine
from app.core.tenant_scope import bind_tenant_scope
from app.documents import template_service
from app.documents.doc_types import get_type
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


def _as_tenant_app(session: Session, tenant_id: int) -> None:
    """Laufzeitrolle hocx_app mit Mandant, wie eine Anfrage in Produktion (RLS aktiv)."""
    session.execute(text("SET LOCAL ROLE hocx_app"))
    bind_tenant_scope(session, tenant_id)


def _make_system_template(session: Session, name: str) -> DocumentTemplate:
    template = DocumentTemplate(tenant_id=None, origin="system", name=name, document_type="protocol", category=get_type("protocol").category, status="active")
    session.add(template)
    session.flush()
    template_service._new_revision(session, template, TemplateContent.model_validate(SIMPLE), status="draft", user_id=None)
    template_service.publish(session, template, user_id=None)
    return template


@pytest.fixture
def ids():
    session = _session()
    try:
        tenant = make_tenant(session, "Archivieren parallel")
        template, _revision = template_service.create_template(session, tenant.id, name="Alt", document_type="protocol", content=TemplateContent.model_validate(SIMPLE))
        template_service.publish(session, template, user_id=None)
        system = _make_system_template(session, "System Archivieren parallel")
        session.commit()
        values = (tenant.id, template.id, system.id)
    finally:
        _close(session)
    yield values
    with engine.connect() as connection:
        connection.execute(text("DELETE FROM document_template_assignment WHERE document_template_id = :sid"), {"sid": values[2]})
        connection.execute(text("UPDATE document_template SET published_revision_id = NULL WHERE id = :sid"), {"sid": values[2]})
        connection.execute(text("DELETE FROM document_template WHERE id = :sid"), {"sid": values[2]})
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


def _archive_while_assignment_pending(tenant_id: int, template_id: int, *, tenant_app: bool) -> bool:
    """Zuweisung schreiben (nicht festschreiben), parallel archivieren, dann festschreiben.
    Liefert, ob das Archivieren auf die Zuweisung gewartet hat."""

    def archive_in_other_request() -> None:
        session = _session()
        try:
            template_service.set_archived(session, session.get(DocumentTemplate, template_id), True, user_id=None)
            session.commit()
        finally:
            _close(session)

    assigner = _session()
    try:
        if tenant_app:
            _as_tenant_app(assigner, tenant_id)
        template_service.set_assignment(assigner, tenant_id, document_type="protocol", template=assigner.get(DocumentTemplate, template_id), brand=None)
        with ThreadPoolExecutor(1) as pool:
            archived = pool.submit(archive_in_other_request)
            blocked = _wait_until_blocked(3.0)  # ohne Sperre läuft das Archivieren sofort durch
            assigner.commit()
            archived.result(timeout=15)
    finally:
        _close(assigner)
    return blocked


def test_archive_while_assignment_is_pending_leaves_no_archived_default(ids):
    tenant_id, template_id, _system_id = ids
    assert _archive_while_assignment_pending(tenant_id, template_id, tenant_app=False)
    assert _assigned_archived(tenant_id) == 0


def test_archive_system_template_while_tenant_assigns_it(ids):
    """Plattform-Admin archiviert eine Systemvorlage, ein Mandant weist sie gleichzeitig unter RLS zu."""
    tenant_id, _template_id, system_id = ids
    assert _archive_while_assignment_pending(tenant_id, system_id, tenant_app=True)
    assert _assigned_archived(tenant_id) == 0


def test_tenant_can_still_assign_active_system_template_under_rls(ids):
    tenant_id, _template_id, system_id = ids
    session = _session()
    try:
        _as_tenant_app(session, tenant_id)
        assignment = template_service.set_assignment(session, tenant_id, document_type="protocol", template=session.get(DocumentTemplate, system_id), brand=None)
        assert assignment is not None and assignment.document_template_id == system_id
        session.commit()
    finally:
        _close(session)


@pytest.mark.parametrize("which", ["tenant", "system"])
def test_assignment_after_concurrent_archive_is_refused(ids, which):
    tenant_id, template_id, system_id = ids
    target_id = template_id if which == "tenant" else system_id
    assigner = _session()
    try:
        if which == "system":
            _as_tenant_app(assigner, tenant_id)
        template = assigner.get(DocumentTemplate, target_id)  # Stand vor dem Archivieren
        archiver = _session()
        try:
            template_service.set_archived(archiver, archiver.get(DocumentTemplate, target_id), True, user_id=None)
            archiver.commit()
        finally:
            _close(archiver)
        with pytest.raises(template_service.TemplateStateError):
            template_service.set_assignment(assigner, tenant_id, document_type="protocol", template=template, brand=None)
        assigner.rollback()
    finally:
        _close(assigner)
    assert _assigned_archived(tenant_id) == 0
