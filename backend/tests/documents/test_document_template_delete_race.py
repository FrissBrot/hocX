"""Nebenläufigkeit: Dokumentvorlage löschen, während ein Export mit dieser Vorlage entsteht.

``delete_template`` löscht nur nie exportierte Mandantenvorlagen - sonst ginge die Herkunft
historischer PDFs verloren (``document_export.template_id`` ist ``ON DELETE SET NULL``). Die
Prüfung «noch kein Export» lief aber ohne Sperre der Vorlage: Ein Export, der gerade gerendert
und gespeichert wird (``_finalize_render``, noch nicht festgeschrieben), ist für die Zählung
unsichtbar. Das Löschen wartete danach nur beim ``DELETE`` selbst auf den Export und setzte dann
dessen ``template_id``/``template_revision_id`` auf NULL - das PDF existiert, seine Vorlage ist
weg. Erwartet: Das Löschen wartet auf den Export und lehnt dann mit «Vorlage in Verwendung» ab.

Wie ``test_document_studio_race.py`` ohne ``db``-Fixture (echte, festgeschriebene Transaktionen).
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import engine
from app.documents import template_service
from app.documents.layout import TemplateContent
from app.models import DocumentTemplate
from app.models.entities import DocumentExport
from tests.factories import make_tenant

SIMPLE = {"masters": [{"id": "default"}], "body": [{"type": "text", "id": "t", "content": {"default": [{"t": "text", "v": "Stand"}]}}]}


def _session() -> Session:
    return Session(bind=engine.connect(), autoflush=False, future=True)


def _close(session: Session) -> None:
    connection = session.connection()
    session.close()
    connection.close()


@pytest.fixture
def tenant_id():
    session = _session()
    try:
        tenant = make_tenant(session, "Vorlage löschen parallel")
        session.commit()
        tid = tenant.id
    finally:
        _close(session)
    yield tid
    with engine.connect() as connection:
        connection.execute(text("DELETE FROM tenant WHERE id = :tid"), {"tid": tid})
        connection.commit()


def _wait_until_blocked(timeout: float = 10.0) -> bool:
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


def test_delete_waits_for_running_export_and_keeps_its_template(tenant_id):
    setup = _session()
    try:
        template, _revision = template_service.create_template(setup, tenant_id, name="Löschen", document_type="protocol", content=TemplateContent.model_validate(SIMPLE))
        published = template_service.publish(setup, template, user_id=None)
        setup.commit()
        template_id, revision_id = template.id, published.id
    finally:
        _close(setup)

    def delete_in_other_request() -> None:
        session = _session()
        try:
            template_service.delete_template(session, session.get(DocumentTemplate, template_id))
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            _close(session)

    exporter = _session()
    try:
        # Export wie in _finalize_render: Zeile geschrieben, Commit steht noch aus
        export = DocumentExport(tenant_id=tenant_id, document_type="protocol", template_id=template_id, template_revision_id=revision_id)
        exporter.add(export)
        exporter.flush()
        export_id = export.id
        with ThreadPoolExecutor(1) as pool:
            deletion = pool.submit(delete_in_other_request)
            blocked = _wait_until_blocked()
            exporter.commit()  # auch ohne Warten, sonst hinge der Thread an der Sperre des Exports
            assert blocked, "Löschen wartet nicht auf den laufenden Export"
            with pytest.raises(template_service.TemplateStateError):
                deletion.result(timeout=15)
    finally:
        _close(exporter)

    with Session(engine) as check:
        assert check.get(DocumentTemplate, template_id) is not None
        saved = check.get(DocumentExport, export_id)
        assert saved.template_id == template_id
        assert saved.template_revision_id == revision_id
