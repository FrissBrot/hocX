from typing import TypeVar

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core import tenant_scope  # noqa: F401  registriert den RLS-Hook (after_begin) für alle Sessions
from app.core.config import settings

# application_name: in pg_stat_activity lassen sich Backend, job-worker, document-worker usw.
# auseinanderhalten (alle nutzen dieselbe Rolle hocx_app).
engine = create_engine(
    settings.app_database_url or settings.database_url,
    future=True,
    pool_pre_ping=True,
    hide_parameters=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout_seconds,
    connect_args={"application_name": f"hocx-{settings.process_kind}"},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


T = TypeVar("T")


def release_for_stream(db: Session, response: T) -> T:
    """Transaktion beenden (und damit die Pool-Verbindung freigeben), bevor eine Datei-/Streaming-
    Antwort gesendet wird. FastAPI beendet yield-Dependencies wie get_db erst nach dem letzten
    Byte - ein langsamer Download hielt sonst eine Verbindung bis zum Ende (Concurrency-Audit
    CONC-002). Commit statt close: die Download-Routen schreiben nichts Unbestätigtes, und die
    Session bleibt für den Rest der Anfrage benutzbar (lädt bei Bedarf neu). Die Antwort selbst
    darf die Session nicht mehr benutzen."""
    db.commit()
    return response
