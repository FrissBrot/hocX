"""initial hocx schema (1.0.0 baseline)

Squashed from the 74 incremental migrations of the 0.x beta series into a single
baseline for the 1.0.0 release. 1.0.0 does not need to upgrade existing beta
installations, so there is no value in keeping that history executable - this
migration produces exactly the schema the old chain converged on (verified by
diffing `pg_dump --schema-only` output of both paths; see
sql/baseline_schema.sql, sql/baseline_lookup_data.sql, sql/baseline_demo_data.sql).

Structure:
  - baseline_schema.sql: all DDL (tables, sequences, functions/triggers, indexes,
    constraints, extensions) plus the GRANTs the two restricted DB roles need.
  - baseline_lookup_data.sql: global lookup/reference rows (role, todo_status,
    element_type, render_type, event_category) - always installed, every
    environment needs them.
  - baseline_demo_data.sql: tenant-scoped demo data (workspaces, the four
    @hocx.local accounts, a starter template) - only installed when a developer
    explicitly opts in with `alembic -x seed_demo=true upgrade head`. Never part
    of the production/release path.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-08-27
"""

import os
from pathlib import Path

import sqlalchemy as sa
from alembic import context, op

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"

APP_ROLE = "hocx_app"
ABGABEBOX_ROLE = "hocx_abgabebox"
APP_ROLE_STATEMENT_TIMEOUT = "30s"


def _read_password(env_var: str, role_name: str) -> str:
    password = os.environ.get(env_var)
    if not password and (password_file := os.environ.get(f"{env_var}_FILE")):
        with open(password_file, encoding="utf-8") as secret_file:
            password = secret_file.read().rstrip("\r\n")
    if not password:
        raise RuntimeError(
            f"{env_var} muss vor dieser Migration gesetzt sein "
            f"(Passwort fuer die restricted Postgres-Rolle '{role_name}')."
        )
    return password


def _execute_raw(sql: str) -> None:
    # op.execute()/exec_driver_sql() route through SQLAlchemy's DBAPI parameter handling,
    # which scans for '%'-style placeholders even when no parameters are bound - and
    # baseline_schema.sql's create_protocol_from_template function body contains a literal
    # '%' (PL/pgSQL's own RAISE format placeholder). Going through the raw psycopg cursor
    # instead (no parameters argument at all) skips that scan entirely, so the DDL reaches
    # Postgres byte-for-byte unmodified - still inside the same connection/transaction alembic
    # is managing, since it's the same underlying DBAPI connection.
    raw_connection = op.get_bind().connection.dbapi_connection
    with raw_connection.cursor() as cursor:
        cursor.execute(sql)


def _create_role(role_name: str, password: str) -> None:
    # CREATE ROLE/ALTER ROLE are DDL and don't support bound parameters at this grammar
    # position. The password comes from a server-side env var (operator-set, not a user
    # input path), so simple quote-escaping is sufficient - no third-party injection risk.
    escaped_password = password.replace("'", "''")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{role_name}') THEN
                CREATE ROLE {role_name} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
                    NOREPLICATION NOBYPASSRLS NOINHERIT;
            END IF;
        END
        $$;
        """
    )
    op.execute(f"ALTER ROLE {role_name} PASSWORD '{escaped_password}'")


def upgrade() -> None:
    # Read both live from the connection instead of POSTGRES_DB/POSTGRES_USER: those env
    # vars aren't reliably in sync with which database/role this migration is actually
    # running as - e.g. docker-compose.yml's backend service has `env_file: .env`, which
    # always loads the *literal* .env file regardless of which --env-file was passed to
    # `docker compose` (e2e/tests use a different one), so POSTGRES_USER there silently
    # leaked the unrelated dev-stack value and broke `ALTER DEFAULT PRIVILEGES FOR ROLE`
    # below with "role ... does not exist". current_database()/current_user can't drift
    # from reality since they *are* the connection's reality.
    bind = op.get_bind()
    db_name = bind.execute(sa.text("SELECT current_database()")).scalar()
    # admin_role is whichever role actually runs this migration - baseline_schema.sql's
    # ALTER DEFAULT PRIVILEGES is scoped to objects *it* creates, i.e. every table/sequence
    # any future migration adds under this role.
    admin_role = bind.execute(sa.text("SELECT current_user")).scalar()

    # Roles must exist before baseline_schema.sql runs - it GRANTs to both of them.
    _create_role(APP_ROLE, _read_password("APP_DB_PASSWORD", APP_ROLE))
    op.execute(f"ALTER ROLE {APP_ROLE} SET statement_timeout = '{APP_ROLE_STATEMENT_TIMEOUT}'")
    op.execute(f"GRANT CONNECT ON DATABASE {db_name} TO {APP_ROLE}")

    _create_role(ABGABEBOX_ROLE, _read_password("ABGABEBOX_DB_PASSWORD", ABGABEBOX_ROLE))
    op.execute(f"GRANT CONNECT ON DATABASE {db_name} TO {ABGABEBOX_ROLE}")

    schema_sql = (SQL_DIR / "baseline_schema.sql").read_text(encoding="utf-8")
    _execute_raw(schema_sql.replace("__ADMIN_ROLE__", admin_role))

    _execute_raw((SQL_DIR / "baseline_lookup_data.sql").read_text(encoding="utf-8"))

    seed_demo = context.get_x_argument(as_dictionary=True).get("seed_demo", "").lower() == "true"
    if seed_demo:
        # Demo identities have public, intentionally well-known credentials. They are only
        # installed when a developer explicitly opts in with `alembic -x seed_demo=true`.
        _execute_raw((SQL_DIR / "baseline_demo_data.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP SCHEMA public CASCADE")
    op.execute("CREATE SCHEMA public")
    op.execute(f"DROP ROLE IF EXISTS {APP_ROLE}")
    op.execute(f"DROP ROLE IF EXISTS {ABGABEBOX_ROLE}")
