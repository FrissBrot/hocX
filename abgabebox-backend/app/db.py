from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

engine = create_engine(settings.database_url, future=True, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# H12 (2026-08-12 Audit): namespace offset for tenant_upload_lock below, kept well clear of the
# small fixed advisory-lock ids (202600001-202600007) used for the cross-process singleton
# background loops in this service's and the main backend's main.py, so the two can never
# collide regardless of tenant_id.
_TENANT_UPLOAD_LOCK_OFFSET = 300_000_000_000


@contextmanager
def tenant_upload_lock(tenant_id: int) -> Iterator[None]:
    """Serializes the storage-quota check-then-write sequence in routes/public.py's upload()
    per tenant (H12 audit finding: tenant_storage_bytes() walks the filesystem with no locking,
    so concurrent uploads within a rate-limit burst can all observe "under quota" before any of
    them has written a byte, together blowing past the per-tenant quota).

    Uses a Postgres advisory lock rather than an in-process asyncio.Lock: this service runs
    `uvicorn ... --workers 2` (see docker-compose.yml) - two separate OS processes, not one - so
    an asyncio.Lock keyed by tenant would only ever coordinate requests landing on the same
    worker and silently miss the other one. Postgres is the one piece of shared state both
    workers already talk to (there is no Redis/similar available to this service, unlike the
    main backend - checked app/config.py and docker-compose.yml's abgabebox-backend service
    environment first). This mirrors the existing pg_advisory_lock/pg_advisory_unlock pattern
    used for this service's own cross-process singleton background loop
    (app/main.py:quarantine_cleanup_loop, lock id 202600007) and the main backend's equivalents -
    advisory locks are a plain function call, not a table grant, so they work fine under the
    'hocx_abgabebox' restricted DB role even though it has no SELECT/UPDATE/DELETE on most
    tables (see backend/alembic/versions/0020_abgabebox.py).

    Deliberately uses the transaction-scoped variant (pg_advisory_xact_lock) on a short-lived,
    dedicated connection separate from the request's own ORM session: routes/public.py's _log()
    helper commits that session multiple times over the course of one request, and a
    session-scoped pg_advisory_lock would need an explicit pg_advisory_unlock in a finally block
    to avoid leaking the lock across requests on that connection if something raised - the xact
    variant instead auto-releases the instant this function's own connection's transaction ends
    (commit, rollback, or the connection simply being closed), so there's nothing to leak.

    Callers should keep the locked block limited to the quota check plus whatever writes
    actually change what tenant_storage_bytes() will see next time (i.e. through the quarantine
    writes) - it does not need to extend through scanning/moving/DB-insert, since a concurrent
    request's own tenant_storage_bytes() call afterwards will already see this request's
    quarantine files sitting on disk.
    """
    lock_key = _TENANT_UPLOAD_LOCK_OFFSET + tenant_id
    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key})
        yield
