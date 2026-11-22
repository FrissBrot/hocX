"""Nebenläufigkeit: Standardvorlage eines Dokumenttyps zweimal gleichzeitig setzen.

``template_service.set_assignment`` sucht die Zuweisung und legt sie an, wenn es keine gibt.
Zwei gleichzeitige erste Zuweisungen (zwei Admins, Doppelklick, «Eigene Gestaltung» einer
Sitzungsvorlage in zwei Tabs) sahen beide keine Zeile; die zweite scheiterte danach am
Unique-Index ``uq_document_template_assignment_tenant`` - ``IntegrityError``, HTTP 500 und ein
Eintrag im Fehlerprotokoll. Erwartet: die zweite wartet und übernimmt die Zeile der ersten.

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
def tenant_id():
    session = _session()
    try:
        tenant = make_tenant(session, "Standardvorlage parallel")
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


def _published_template(tenant_id: int, name: str) -> int:
    session = _session()
    try:
        template, _revision = template_service.create_template(session, tenant_id, name=name, document_type="protocol", content=TemplateContent.model_validate(SIMPLE))
        template_service.publish(session, template, user_id=None)
        session.commit()
        return template.id
    finally:
        _close(session)


def _assign(session: Session, tenant_id: int, template_id: int) -> None:
    template = session.get(DocumentTemplate, template_id)
    template_service.set_assignment(session, tenant_id, document_type="protocol", template=template, brand=None)


def test_parallel_first_assignments_do_not_fail(tenant_id):
    first_id = _published_template(tenant_id, "Erste")
    second_id = _published_template(tenant_id, "Zweite")

    def assign_in_other_request() -> None:
        session = _session()
        try:
            _assign(session, tenant_id, second_id)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            _close(session)

    first = _session()
    try:
        _assign(first, tenant_id, first_id)  # Zeile geschrieben, Commit steht noch aus
        with ThreadPoolExecutor(1) as pool:
            second = pool.submit(assign_in_other_request)
            blocked = _wait_until_blocked()
            first.commit()  # auch ohne Warten, sonst hinge der Thread am Lock der ersten
            assert blocked, "Zweite Zuweisung wartet nicht auf die erste"
            second.result(timeout=15)  # vorher: IntegrityError (uq_document_template_assignment_tenant)
    finally:
        _close(first)

    with Session(engine) as check:
        rows = check.scalars(
            select(DocumentTemplateAssignment).where(
                DocumentTemplateAssignment.tenant_id == tenant_id,
                DocumentTemplateAssignment.document_type == "protocol",
                DocumentTemplateAssignment.protocol_template_id.is_(None),
            )
        ).all()
        assert len(rows) == 1
        # Wer zuletzt festschreibt, gewinnt - wie bei einer bestehenden Zuweisung
        assert rows[0].document_template_id == second_id
        assert check.scalar(select(func.count(DocumentTemplateAssignment.id)).where(DocumentTemplateAssignment.tenant_id == tenant_id)) == 1
