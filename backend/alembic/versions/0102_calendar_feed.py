"""Kalender-Abos ("Verknuepfungen"): pro Benutzer je ein abonnierbarer iCal-Feed fuer Termine
und fuer Todos, den Apple Kalender/Google Kalender ueber eine geheime URL abrufen
(<app-domain>/api/public/calendar/<token>.ics).

Der Token ist wie bei share_link selbst die Authentifizierung, wird hier aber nicht im Klartext
gespeichert: token_hash (SHA-256) dient dem Nachschlagen beim Abruf, token_encrypted (Fernet via
secret_crypto) nur dem erneuten Anzeigen der URL in den Einstellungen - ein Datenbank-Leak allein
reicht so nicht, um fremde Feeds abzurufen, solange ADMIN_AUTH_SECRET nicht mit abfliesst.

calendar_name wird vom Frontend in der UI-Sprache mitgegeben (das Backend hat bewusst keine
eigene Sprachliste, siehe CLAUDE.md i18n-Regeln).

hocx_app hat bereits table-wide DML auf neuen Tabellen via ALTER DEFAULT PRIVILEGES (siehe
0066/0068) - kein neues GRANT noetig.

Revision ID: 0102_calendar_feed
Revises: 0101_session_notes_element_type
Create Date: 2026-10-10
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0102_calendar_feed"
down_revision = "0101_session_notes_element_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "calendar_feed",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("uuidv7()")),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("calendar_name", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("token_encrypted", sa.Text(), nullable=False),
        sa.Column("token_created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("todo_scope", sa.Text(), nullable=False, server_default=sa.text("'mine'")),
        sa.Column("include_completed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("hide_details", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("public_id", name="uq_calendar_feed_public_id"),
        sa.UniqueConstraint("token_hash", name="uq_calendar_feed_token_hash"),
        sa.UniqueConstraint("user_id", "kind", name="uq_calendar_feed_user_kind"),
        sa.CheckConstraint("kind IN ('events', 'todos')", name="ck_calendar_feed_kind"),
        sa.CheckConstraint("todo_scope IN ('mine', 'all')", name="ck_calendar_feed_todo_scope"),
    )
    op.create_index("idx_calendar_feed_tenant", "calendar_feed", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("calendar_feed")
