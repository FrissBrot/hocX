"""S3-003: Die öffentlich erreichbare Abgabebox (Rolle hocx_abgabebox) darf über die
SECURITY-DEFINER-Funktionen weder die Konfiguration (samt Zugangsdaten) eines anderen Dienstes
abrufen noch Journaleinträge für den Namespace "main" schreiben (Migration 0115)."""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db import engine


def test_abgabebox_role_gets_its_own_storage_config():
    with engine.connect() as conn:
        assert conn.execute(text("SELECT session_user")).scalar() == "hocx_abgabebox"
        row = conn.execute(text("SELECT * FROM storage_active_config('abgabebox')")).one()
        assert row.profile_id is not None


@pytest.mark.parametrize("service", ["backend", "photo-worker"])
def test_abgabebox_role_cannot_read_other_services_storage_config(service):
    with engine.connect() as conn:
        with pytest.raises(DBAPIError, match="not permitted"):
            conn.execute(text("SELECT * FROM storage_active_config(:s)"), {"s": service}).one()


def test_abgabebox_role_cannot_register_writes_in_the_main_namespace():
    with engine.connect() as conn:
        generation = conn.execute(text("SELECT generation FROM storage_begin_write()")).scalar()
        with pytest.raises(DBAPIError, match="not permitted"):
            conn.execute(
                text("SELECT storage_register_write('main', 'uploads/tenant-1/x.bin', 'delete', NULL, NULL, NULL, :g)"),
                {"g": generation},
            )
        conn.rollback()
