"""Altbestand des Upload-Verlaufs rekonstruieren (einmalig nach dem Update auf 1.6, idempotent).

    python -m app.workers.upload_history_backfill [--tenant <tenant-public-id>]

Einmaliger Wartungsbefehl, kein periodischer Job (deshalb nicht über scripts/run_job.sh und nicht
in job_registry): ``docker compose -p <projekt> exec -T backend python -m
app.workers.upload_history_backfill`` (RUNBOOK). Je Mandant eine Reihe kurzer Transaktionen; ein
Abbruch lässt sich durch erneutes Starten fortsetzen. Ausgabe nur Zählungen, keine
Dateinamen oder Personendaten.
"""

from __future__ import annotations

import argparse
import sys
import uuid

from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.tenant_scope import bind_tenant_scope
from app.models.entities import Tenant
from app.services.upload_history_backfill import backfill_tenant


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Upload-Verlauf: Altbestand rekonstruieren")
    parser.add_argument("--tenant", help="nur dieser Mandant (öffentliche ID)")
    args = parser.parse_args(argv)
    total_jobs = total_files = 0
    with SessionLocal() as db:
        query = select(Tenant.id, Tenant.public_id).order_by(Tenant.id)
        if args.tenant:
            query = query.where(Tenant.public_id == uuid.UUID(args.tenant))
        tenants = db.execute(query).all()
        for tenant_id, public_id in tenants:
            # Je Mandant gebunden (RLS wie ein Request dieses Mandanten)
            bind_tenant_scope(db, tenant_id)
            db.commit()
            report = backfill_tenant(db, tenant_id)
            jobs = sum(report.jobs.values())
            total_jobs += jobs
            total_files += report.files
            if jobs:
                print(f"{public_id}: {jobs} Vorgänge, {report.files} Dateien ({', '.join(f'{k}={v}' for k, v in sorted(report.jobs.items()))})")
        bind_tenant_scope(db, None)
    print(f"Upload-Verlauf rekonstruiert: {total_jobs} Vorgänge, {total_files} Dateien")
    return 0


if __name__ == "__main__":
    sys.exit(main())
