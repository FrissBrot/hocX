"""enables pg_stat_statements (audit finding, 2026-08-26: no way to see which queries were
actually expensive/frequent in production). shared_preload_libraries is set via the `db`
service's command in docker-compose.yml/docker-compose.release.yml - that part only takes
effect on a full Postgres restart (it's a postmaster-start-time setting, can't be changed
via ALTER SYSTEM), so the `db` container must already be running with the updated command
by the time this migration runs, or CREATE EXTENSION below fails. Restricted app role
(hocx_app, see 0070_restrict_app_db_role.py) is deliberately not granted anything here -
reading pg_stat_statements is an operator/DBA activity (`docker compose exec db psql ...`
as the admin role), not something the running application needs.

Revision ID: 0072_pg_stat_statements
Revises: 0071_missing_fk_indexes
Create Date: 2026-08-26
"""

from alembic import op

revision = "0072_pg_stat_statements"
down_revision = "0071_missing_fk_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_stat_statements")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS pg_stat_statements")
