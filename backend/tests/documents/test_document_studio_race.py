"""STUDIO-002: Die optimistische Sperre (``lock_version``) muss auch bei echter Parallelität
greifen. Zwei gleichzeitige Speicherungen mit derselben Version: genau eine gewinnt, die andere
erhält einen Konflikt - nie stilles Überschreiben und nie ``IntegrityError`` (HTTP 500).

Wie ``tests/test_fines_collect_race.py`` bewusst ohne die ``db``-Fixture: Zeilensperren zwischen
zwei Verbindungen lassen sich nur mit echten, festgeschriebenen Transaktionen prüfen. Die Daten
werden deshalb committet und am Ende über ``DELETE FROM tenant`` (Cascade) entfernt.

Damit der Wettlauf deterministisch auftritt, verzögert der Test das Lesen des Stands
(``draft_revision`` bzw. die Asset-Prüfung nach der Versionsprüfung). Ohne Zeilensperre lesen
beide Threads währenddessen denselben Stand.
"""
from __future__ import annotations

import threading
import time

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.db import engine
from app.documents import brand_service, template_service
from app.documents.brand import BrandTokens
from app.documents.layout import TemplateContent
from app.models import DocumentBrand, DocumentTemplate, DocumentTemplateRevision
from tests.factories import make_tenant

SIMPLE = {"masters": [{"id": "default"}], "body": [{"type": "text", "id": "t", "content": {"default": [{"t": "text", "v": "Stand"}]}}]}
DELAY = 0.3


def _session() -> Session:
    return Session(bind=engine.connect(), autoflush=False, future=True)


def _close(session: Session) -> None:
    connection = session.connection()
    session.close()
    connection.close()


def _cleanup(tenant_id: int) -> None:
    with engine.connect() as connection:
        connection.execute(text("DELETE FROM tenant WHERE id = :tid"), {"tid": tenant_id})
        connection.commit()


@pytest.fixture
def tenant_id():
    session = _session()
    try:
        tenant = make_tenant(session, "Studio-Race")
        session.commit()
        tid = tenant.id
    finally:
        _close(session)
    yield tid
    _cleanup(tid)


def _content(label: str) -> TemplateContent:
    data = {**SIMPLE, "body": [{"type": "text", "id": "t", "content": {"default": [{"t": "text", "v": label}]}}]}
    return TemplateContent.model_validate(data)


def _create_template(tenant_id: int, *, publish: bool) -> tuple[int, int]:
    session = _session()
    try:
        template, revision = template_service.create_template(session, tenant_id, name="Race", document_type="protocol", content=_content("Start"))
        if publish:
            template_service.publish(session, template, user_id=None)
        session.commit()
        return template.id, revision.lock_version
    finally:
        _close(session)


def _slow(monkeypatch, module, name: str) -> None:
    original = getattr(module, name)

    def delayed(*args, **kwargs):
        result = original(*args, **kwargs)
        time.sleep(DELAY)
        return result

    monkeypatch.setattr(module, name, delayed)


def _run_parallel(work) -> dict[str, object]:
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}

    def worker(name: str) -> None:
        session = _session()
        try:
            barrier.wait(timeout=5)
            results[name] = work(session, name)
            session.commit()
        except Exception as exc:  # noqa: BLE001 - Ergebnis wird im Test ausgewertet
            session.rollback()
            results[name] = exc
        finally:
            _close(session)

    threads = [threading.Thread(target=worker, args=(name,)) for name in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    return results


def test_parallel_draft_saves_with_same_lock_version_conflict(tenant_id, monkeypatch):
    template_id, lock = _create_template(tenant_id, publish=False)
    _slow(monkeypatch, template_service, "draft_revision")

    def work(session: Session, name: str):
        template = session.get(DocumentTemplate, template_id)
        return template_service.save_draft(session, template, _content(name), expected_lock_version=lock, user_id=None).lock_version

    results = _run_parallel(work)
    conflicts = [value for value in results.values() if isinstance(value, template_service.TemplateConflictError)]
    saved = [value for value in results.values() if isinstance(value, int)]
    assert len(conflicts) == 1 and saved == [lock + 1], results
    with engine.connect() as connection:
        version = connection.execute(text("SELECT lock_version FROM document_template_revision WHERE template_id = :id AND status = 'draft'"), {"id": template_id}).scalar_one()
    assert version == lock + 1


def test_parallel_first_drafts_do_not_fail(tenant_id, monkeypatch):
    template_id, _lock = _create_template(tenant_id, publish=True)
    _slow(monkeypatch, template_service, "draft_revision")

    def work(session: Session, name: str):
        template = session.get(DocumentTemplate, template_id)
        return template_service.save_draft(session, template, _content(name), expected_lock_version=None, user_id=None).revision_no

    results = _run_parallel(work)
    assert all(isinstance(value, int) for value in results.values()), results
    with engine.connect() as connection:
        drafts = connection.execute(text("SELECT count(*) FROM document_template_revision WHERE template_id = :id AND status = 'draft'"), {"id": template_id}).scalar_one()
    assert drafts == 1


def test_parallel_brand_updates_with_same_lock_version_conflict(tenant_id, monkeypatch):
    session = _session()
    try:
        brand = brand_service.create_brand(session, tenant_id, name="Race", tokens=BrandTokens())
        session.commit()
        brand_id, lock = brand.id, brand.lock_version
    finally:
        _close(session)
    _slow(monkeypatch, brand_service, "_check_asset_refs")

    def work(session: Session, name: str):
        brand = session.get(DocumentBrand, brand_id)
        tokens = BrandTokens.model_validate({"colors": {"primary": "#112233" if name == "a" else "#445566"}})
        return brand_service.update_brand(session, brand, expected_lock_version=lock, tokens=tokens, user_id=None).lock_version

    results = _run_parallel(work)
    conflicts = [value for value in results.values() if isinstance(value, brand_service.BrandConflictError)]
    saved = [value for value in results.values() if isinstance(value, int)]
    assert len(conflicts) == 1 and saved == [lock + 1], results


def test_parallel_restore_and_save_share_one_draft(tenant_id, monkeypatch):
    template_id, _lock = _create_template(tenant_id, publish=True)
    session = _session()
    try:
        published_id = session.scalar(select(DocumentTemplateRevision.id).where(DocumentTemplateRevision.template_id == template_id))
    finally:
        _close(session)
    _slow(monkeypatch, template_service, "draft_revision")

    def work(session: Session, name: str):
        template = session.get(DocumentTemplate, template_id)
        if name == "a":
            return template_service.restore_revision(session, template, session.get(DocumentTemplateRevision, published_id), user_id=None).revision_no
        return template_service.save_draft(session, template, _content(name), expected_lock_version=None, user_id=None).revision_no

    results = _run_parallel(work)
    assert all(isinstance(value, int) for value in results.values()), results
