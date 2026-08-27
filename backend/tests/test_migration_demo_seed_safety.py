from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_base_migration_requires_explicit_demo_seed_opt_in():
    migration = (BACKEND_ROOT / "alembic/versions/0001_initial_schema.py").read_text()
    assert 'get("seed_demo", "").lower() == "true"' in migration
    assert "sql.partition(seed_marker)" in migration


def test_legacy_demo_accounts_are_revoked_by_default():
    migration = (BACKEND_ROOT / "alembic/versions/0074_disable_legacy_demo_accounts.py").read_text()
    for email in ("admin@hocx.local", "writer@hocx.local", "reader@hocx.local"):
        assert email in migration
    assert "SET is_active = FALSE" in migration


def test_production_startup_has_a_second_demo_account_barrier():
    main = (BACKEND_ROOT / "app/main.py").read_text()
    assert "ensure_no_production_demo_data()" in main
    assert "Production startup blocked: local demo identities exist" in main
    assert '"hocX Workspace", "Regional Workspace"' in main
