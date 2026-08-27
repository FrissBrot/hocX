from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_base_migration_requires_explicit_demo_seed_opt_in():
    migration = (BACKEND_ROOT / "alembic/versions/0001_initial_schema.py").read_text()
    assert 'get("seed_demo", "").lower() == "true"' in migration
    # Demo data lives in its own SQL file, only executed inside the seed_demo branch -
    # unlike lookup data, it must never run on the production/release path.
    assert "if seed_demo:" in migration
    assert '"baseline_demo_data.sql"' in migration

    demo_sql = (BACKEND_ROOT / "sql/baseline_demo_data.sql").read_text()
    for email in ("admin@hocx.local", "writer@hocx.local", "reader@hocx.local"):
        assert email in demo_sql


def test_production_startup_has_a_second_demo_account_barrier():
    main = (BACKEND_ROOT / "app/main.py").read_text()
    assert "ensure_no_production_demo_data()" in main
    assert "Production startup blocked: local demo identities exist" in main
    assert '"hocX Workspace", "Regional Workspace"' in main
