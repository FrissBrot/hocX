from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core import tenant_scope  # noqa: F401  registriert den RLS-Hook (after_begin) für alle Sessions
from app.core.config import settings

engine = create_engine(settings.app_database_url or settings.database_url, future=True, pool_pre_ping=True, hide_parameters=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

