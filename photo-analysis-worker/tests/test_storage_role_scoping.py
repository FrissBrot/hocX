"""S3-003: Die Rolle hocx_photo_worker bekommt über storage_active_config nur die eigene
Konfiguration, nie die des Backends oder der Abgabebox (Migration 0115)."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db import build_engine


def test_photo_worker_role_gets_its_own_storage_config():
    with build_engine().connect() as conn:
        assert conn.execute(text("SELECT session_user")).scalar() == "hocx_photo_worker"
        assert conn.execute(text("SELECT * FROM storage_active_config('photo-worker')")).one().profile_id is not None


@pytest.mark.parametrize("service", ["backend", "abgabebox"])
def test_photo_worker_role_cannot_read_other_services_storage_config(service):
    with build_engine().connect() as conn:
        with pytest.raises(DBAPIError, match="not permitted"):
            conn.execute(text("SELECT * FROM storage_active_config(:s)"), {"s": service}).one()
