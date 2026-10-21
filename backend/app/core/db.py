from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core import tenant_scope  # noqa: F401  registriert den RLS-Hook (after_begin) für alle Sessions
from app.core.config import settings

# application_name: in pg_stat_activity lassen sich Backend, job-worker, document-worker usw.
# auseinanderhalten (alle nutzen dieselbe Rolle hocx_app).
engine = create_engine(
    settings.app_database_url or settings.database_url,
    future=True,
    pool_pre_ping=True,
    hide_parameters=True,
    connect_args={"application_name": f"hocx-{settings.process_kind}"},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
