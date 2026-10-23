"""PDF-Export als Auftrag (Concurrency-Audit Paket 10, Migration 0150): Anlegen, faire Vergabe,
ein laufender Auftrag je Protokoll, Zugriff nur auf eigene Aufträge, Auto-PDF nach dem
Abschliessen, Wiederholung bei vorübergehenden Renderfehlern."""

import asyncio
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.api.routes import documents as routes
from app.api.routes import protocols as protocol_routes
from app.documents.renderer import DocumentRenderError
from app.documents.service import DocumentRequest
from app.models.document_entities import DocumentRenderJob
from app.schemas.protocol import ProtocolUpdate
from app.services import document_render_jobs
from tests.factories import make_app_user, make_current_user, make_protocol, make_template, make_tenant


def _world(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id, status="durchgeführt")
    account = make_app_user(db, email=f"writer-{uuid.uuid4().hex[:8]}@example.com", tenant_id=tenant.id, role_code="writer")
    user = make_current_user(tenant.id, role="writer", user_id=account.id)
    return tenant, protocol, user


def _job(db, tenant_id, protocol_id=None, status="queued"):
    job = DocumentRenderJob(tenant_id=tenant_id, protocol_id=protocol_id, request_json={"n": uuid.uuid4().hex}, status=status)
    db.add(job)
    db.flush()
    return job


def test_render_route_enqueues_and_double_click_reuses_the_job(db):
    _tenant, protocol, user = _world(db)
    body = DocumentRequest(protocol_id=protocol.public_id)
    first = asyncio.run(routes.render_document(body, db=db, user=user))
    second = asyncio.run(routes.render_document(body, db=db, user=user))
    assert first.status == "queued"
    assert first.id == second.id


def test_render_route_rejects_foreign_protocol_immediately(db):
    _tenant, protocol, _user = _world(db)
    _other_tenant, _other_protocol, other_user = _world(db)
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(routes.render_document(DocumentRequest(protocol_id=protocol.public_id), db=db, user=other_user))
    assert excinfo.value.status_code == 404
    assert db.scalar(text("SELECT count(*) FROM document_render_job WHERE tenant_id = :t"), {"t": other_user.current_tenant_id}) == 0


def test_job_status_is_only_visible_to_its_requester(db):
    tenant, protocol, user = _world(db)
    job = asyncio.run(routes.render_document(DocumentRequest(protocol_id=protocol.public_id), db=db, user=user))
    colleague = make_current_user(tenant.id, role="writer", user_id=make_app_user(db, email=f"c-{uuid.uuid4().hex[:8]}@example.com", tenant_id=tenant.id, role_code="writer").id)
    with pytest.raises(HTTPException) as excinfo:
        routes.get_render_job(job.id, db=db, user=colleague)
    assert excinfo.value.status_code == 404
    assert routes.get_render_job(job.id, db=db, user=user).status == "queued"


def test_claim_prefers_idle_tenants_and_never_runs_a_protocol_twice(db):
    db.execute(text("UPDATE document_render_job SET status = 'done' WHERE status IN ('queued', 'running')"))
    busy_tenant, busy_protocol, _ = _world(db)
    idle_tenant, idle_protocol, _ = _world(db)
    _job(db, busy_tenant.id, busy_protocol.id, status="running")
    same_protocol = _job(db, busy_tenant.id, busy_protocol.id)          # ältester, aber Protokoll läuft schon
    other_busy = _job(db, busy_tenant.id)                                # Mandant hat schon einen laufenden
    idle = _job(db, idle_tenant.id, idle_protocol.id)                    # jüngster, Mandant frei
    assert document_render_jobs.claim_next(db) == idle.id
    assert document_render_jobs.claim_next(db) == other_busy.id
    assert document_render_jobs.claim_next(db) is None                    # nur noch das laufende Protokoll
    assert db.get(DocumentRenderJob, same_protocol.id).status == "queued"


def test_busy_renderer_puts_the_job_back_into_the_queue(db, monkeypatch):
    _tenant, protocol, user = _world(db)
    job = asyncio.run(routes.render_document(DocumentRequest(protocol_id=protocol.public_id), db=db, user=user))

    async def busy(*args, **kwargs):
        raise DocumentRenderError("error.busy")

    monkeypatch.setattr("app.documents.service.render", busy)
    db.execute(text("UPDATE document_render_job SET status = 'running', attempts = 1 WHERE id = :id"), {"id": job.id})
    asyncio.run(document_render_jobs.run_job(job.id, db=db))
    assert db.get(DocumentRenderJob, job.id).status == "queued"

    db.execute(text("UPDATE document_render_job SET status = 'running', attempts = :n WHERE id = :id"), {"id": job.id, "n": document_render_jobs.MAX_ATTEMPTS})
    asyncio.run(document_render_jobs.run_job(job.id, db=db))
    refreshed = routes.get_render_job(job.id, db=db, user=user)
    assert refreshed.status == "failed" and refreshed.error_status == 503


def test_closing_a_protocol_queues_its_pdf(db):
    tenant, protocol, user = _world(db)
    protocol_routes.patch_protocol(protocol.public_id, ProtocolUpdate(status="abgeschlossen"), db=db, user=user)
    queued = db.scalar(text("SELECT count(*) FROM document_render_job WHERE protocol_id = :p AND requested_by IS NULL"), {"p": protocol.id})
    assert queued == 1


def test_jobs_of_blocked_accounts_are_not_rendered(db):
    """Security-Review Paket 10: ein nach dem Anlegen gesperrtes Konto rendert nicht mehr."""
    from app.models import AppUser

    _tenant, protocol, user = _world(db)
    job = asyncio.run(routes.render_document(DocumentRequest(protocol_id=protocol.public_id), db=db, user=user))
    db.get(AppUser, user.user_id).login_enabled = False
    db.flush()
    asyncio.run(document_render_jobs.run_job(job.id, db=db))
    stored = db.get(DocumentRenderJob, job.id)
    assert stored.status == "failed" and stored.error_status == 403 and stored.export_id is None


def test_finished_jobs_are_removed_by_retention(db):
    from app.services import retention_service

    assert any(rule.table == "document_render_job" for rule in retention_service.RULES)
