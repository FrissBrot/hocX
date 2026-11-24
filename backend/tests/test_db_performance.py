"""Migration 0135_db_performance: Fremdschlüssel-Indizes und Timeouts der Laufzeitrollen."""

import importlib.util
from pathlib import Path

from sqlalchemy import text

from app.backup.restore_core import APP_ROLE_SETTINGS


def _migration():
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0135_db_performance.py"
    spec = importlib.util.spec_from_file_location("db_performance", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_foreign_key_indexes_exist(db):
    migration = _migration()
    expected = {migration._index_name(table, column) for table, column, _partial in migration.FOREIGN_KEY_INDEXES}
    present = set(db.scalars(text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND indexname = ANY(:n)"), {"n": list(expected)}))
    assert present == expected


def test_role_timeouts_are_set_and_restore_sets_the_same(db):
    migration = _migration()
    # hocx_geo kam erst mit 0260_photo_places dazu (setzt dort denselben Timeout); die übrigen
    # Rollen stellt die Wiederherstellung wie 0135 ein
    assert migration.ROLE_SETTINGS == {role: value for role, value in APP_ROLE_SETTINGS.items() if role != "hocx_geo"}
    for role, settings in APP_ROLE_SETTINGS.items():
        config = db.scalar(text("SELECT rolconfig FROM pg_roles WHERE rolname = :role"), {"role": role}) or []
        for name, value in settings.items():
            assert f"{name}={value}" in config, (role, config)
