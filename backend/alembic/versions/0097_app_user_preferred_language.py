"""Add app_user.preferred_language

Modell-Spalte (app/models/entities.py AppUser.preferred_language) wurde im Zuge der
i18n-Migration ergaenzt und landete korrekt in sql/baseline_schema.sql, aber ohne
begleitende Alembic-Migration - jede Query, die AppUser laedt (praktisch jeder
authentifizierte Request, u.a. GET /api/auth/session), schlug auf einer bereits laufenden,
inkrementell migrierten Datenbank mit "column app_user.preferred_language does not exist" fehl
(0001_initial_schema wurde dort schon vor der baseline_schema.sql-Aenderung angewendet).

Auf einer frischen Datenbank (CI, e2e, neues Dev-Setup) hat 0001_initial_schema die Spalte
dagegen schon ueber die aktuelle baseline_schema.sql - ein unbedingtes ADD COLUMN hier wuerde
dort mit DuplicateColumn fehlschlagen (so beim lokalen Nachstellen auf einer frisch
initialisierten Test-DB gefunden). Die Existenzprüfung macht die Migration fuer beide Faelle
sicher, statt zwei unterschiedliche Bootstrap-Pfade dauerhaft auseinanderlaufen zu lassen.

Revision ID: 0097_app_user_preferred_language
Revises: 0096_album_item_share_pending
Create Date: 2026-10-04
"""

import sqlalchemy as sa
from alembic import op

revision = "0097_app_user_preferred_language"
down_revision = "0096_album_item_share_pending"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing_columns = {col["name"] for col in inspector.get_columns("app_user")}
    if "preferred_language" not in existing_columns:
        op.add_column(
            "app_user",
            sa.Column("preferred_language", sa.Text(), nullable=False, server_default=sa.text("'de'")),
        )


def downgrade() -> None:
    op.drop_column("app_user", "preferred_language")
