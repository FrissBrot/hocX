"""restrict main app DB role: adds a least-privilege 'hocx_app' role for the FastAPI
runtime connection, instead of it serving every request as the Postgres superuser
(POSTGRES_USER/'hocx').

Audit finding, 2026-08-26: the main backend connected to Postgres with the bootstrap
'hocx' role, which the official postgres image always creates as superuser (Superuser,
Createrole, Createdb, Replication, Bypass RLS). A SQL-injection bug or a compromised
backend process would therefore have had full control over the entire Postgres server -
all databases, not just this app's - not just this app's tables. 'hocx_abgabebox'
(0020_abgabebox.py) already established the least-privilege pattern for the separate
Abgabebox service; this does the same for the main app.

Unlike hocx_abgabebox's narrow, per-table/per-column allowlist (appropriate for a public,
unauthenticated service), the main app legitimately needs broad read/write access across
almost every table - it's the primary business app, not a narrow public endpoint. So this
grants full DML (SELECT/INSERT/UPDATE/DELETE) on all current tables plus sequence usage,
and - via ALTER DEFAULT PRIVILEGES - on any tables/sequences future migrations create
under the admin role, so later migrations don't each need their own follow-up grant
migration (unlike hocx_abgabebox's history: 0021/0022/0023/0035/0069 were all follow-up
grants for things 0020 didn't yet cover). What this role does NOT get, matching hocx's
current superuser attributes it must NOT retain: SUPERUSER, CREATEDB, CREATEROLE,
REPLICATION, BYPASSRLS. Migrations themselves keep running as the admin role (DATABASE_URL,
unchanged) - only the runtime connection (app/core/db.py, APP_DATABASE_URL) switches to
this role. See app/core/config.py's app_database_url for the fallback behaviour when
APP_DATABASE_URL isn't set (local/CI setups that only define DATABASE_URL keep working
unchanged, still on the admin role, since hardening those isn't this migration's goal).

Also sets statement_timeout on the new role (audit finding, 2026-08-26: statement_timeout
was 0/disabled everywhere - a single expensive/hung query, e.g. from a missing index or
DoS attempt, could run unbounded and hold locks/connections indefinitely). Scoped to this
role rather than globally so it doesn't affect the admin role's migrations, pg_dump, or
maintenance.

Revision ID: 0070_restrict_app_db_role
Revises: 0069_abgabebox_public_id_grant
Create Date: 2026-08-26
"""

import os

from alembic import op

revision = "0070_restrict_app_db_role"
down_revision = "0069_abgabebox_public_id_grant"
branch_labels = None
depends_on = None

ROLE_NAME = "hocx_app"
STATEMENT_TIMEOUT = "30s"


def _read_password(env_var: str) -> str:
    password = os.environ.get(env_var)
    if not password and (password_file := os.environ.get(f"{env_var}_FILE")):
        with open(password_file, encoding="utf-8") as secret_file:
            password = secret_file.read().rstrip("\r\n")
    if not password:
        raise RuntimeError(
            f"{env_var} muss vor dieser Migration gesetzt sein "
            f"(Passwort fuer die restricted Postgres-Rolle '{ROLE_NAME}')."
        )
    return password


def upgrade() -> None:
    password = _read_password("APP_DB_PASSWORD")
    db_name = os.environ.get("POSTGRES_DB", "hocx")
    # admin_role is whichever role actually runs this migration (POSTGRES_USER, 'hocx' by
    # default) - ALTER DEFAULT PRIVILEGES is scoped to objects *it* creates, which is every
    # table/sequence any future migration adds, since migrations always run as this role.
    admin_role = os.environ.get("POSTGRES_USER", "hocx")
    # CREATE ROLE/ALTER ROLE are DDL and don't support bound parameters at this grammar
    # position. The password comes from a server-side env var (operator-set, not a user
    # input path) - simple quote-escaping is sufficient, same reasoning as 0020_abgabebox.
    escaped_password = password.replace("'", "''")

    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{ROLE_NAME}') THEN
                CREATE ROLE {ROLE_NAME} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
                    NOREPLICATION NOBYPASSRLS NOINHERIT;
            END IF;
        END
        $$;
        """
    )
    op.execute(f"ALTER ROLE {ROLE_NAME} PASSWORD '{escaped_password}'")
    op.execute(f"ALTER ROLE {ROLE_NAME} SET statement_timeout = '{STATEMENT_TIMEOUT}'")

    op.execute(f"GRANT CONNECT ON DATABASE {db_name} TO {ROLE_NAME}")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {ROLE_NAME}")

    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {ROLE_NAME}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {ROLE_NAME}")

    op.execute(
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {admin_role} IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {ROLE_NAME}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {admin_role} IN SCHEMA public "
        f"GRANT USAGE, SELECT ON SEQUENCES TO {ROLE_NAME}"
    )


def downgrade() -> None:
    admin_role = os.environ.get("POSTGRES_USER", "hocx")
    op.execute(
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {admin_role} IN SCHEMA public "
        f"REVOKE USAGE, SELECT ON SEQUENCES FROM {ROLE_NAME}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {admin_role} IN SCHEMA public "
        f"REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {ROLE_NAME}"
    )
    op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {ROLE_NAME}")
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {ROLE_NAME}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {ROLE_NAME}")
    db_name = os.environ.get("POSTGRES_DB", "hocx")
    op.execute(f"REVOKE CONNECT ON DATABASE {db_name} FROM {ROLE_NAME}")
    op.execute(f"DROP ROLE IF EXISTS {ROLE_NAME}")
