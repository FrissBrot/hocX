"""PDF-Export in Tests: Auftrag anlegen (Route) und sofort mit der Test-Session ausführen, wie es
der job-worker täte (services/document_render_jobs.py)."""
import asyncio

from fastapi import HTTPException

from app.api.routes import documents as routes
from app.services import document_render_jobs


def render_now(body, *, db, user):
    job = asyncio.run(routes.render_document(body, db=db, user=user))
    asyncio.run(document_render_jobs.run_job(job.id, db=db))
    result = routes.get_render_job(job.id, db=db, user=user)
    if result.status != "done":
        raise HTTPException(status_code=result.error_status or 500, detail=result.error)
    return result.export
