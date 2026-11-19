"""Papierkorb für Dateien und Bilder (Soft-Delete auf stored_file).

Löschen auf der Dateien-/Fotos-Seite legt eine Datei in den Papierkorb (``deleted_at``,
``deleted_by``), statt sie sofort zu entfernen. Alle Verknüpfungen (Galerie-Eintrag, Alben, Tags,
Termin-/Abgabe-/Zyklus-Bezug, Freigabelinks) bleiben stehen, damit «Wiederherstellen» alles
zurückbringt. Das Backend blendet solche Zeilen aus jeder ORM-Abfrage aus
(``app/core/trash_scope.py``); endgültig löscht ``file_trash_service`` nach 30 Tagen
(Job ``file_trash_purge``) oder von Hand.

Laufzeitrollen: hocx_abgabebox und hocx_photo_worker setzen keinen Mandanten-/Papierkorb-Kontext.
Eine RESTRICTIVE-Policy nur für diese beiden Rollen versteckt Papierkorb-Zeilen für SELECT,
UPDATE und DELETE (Abgabebox-Duplikatprüfung, Foto-Worker liest/schreibt keine gelöschten
Dateien). Neue Zeilen der Abgabebox (``deleted_at`` NULL) erfüllen die Bedingung weiterhin. Die
Rolle hocx_app bleibt unverändert: Purge, DSGVO-Löschung und Speicherverwaltung müssen
Papierkorb-Zeilen sehen.

Kontingent: Papierkorb-Dateien belegen weiter Speicher und zählen bis zum endgültigen Löschen ins
Kontingent (``hocx_abgabebox_tenant_storage_bytes`` u. a. summieren ohnehin alle Zeilen).

Downgrade: Papierkorb-Einträge werden **wiederhergestellt** (die Spalten fallen weg, die Dateien
sind wieder sichtbar). Endgültiges Löschen ginge hier nicht vollständig, weil Speicherobjekte,
Vorschaubilder und das Löschjournal nur die Anwendung abräumen kann - eine Zeile ohne Objekt
oder ein Objekt ohne Zeile wäre schlechter als eine zurückgeholte Datei.

Revision ID: 0199_stored_file_soft_delete
Revises: 0198_submission_manual_elements
Create Date: 2026-11-19
"""

import sqlalchemy as sa
from alembic import op

revision = "0199_stored_file_soft_delete"
down_revision = "0198_submission_manual_elements"
branch_labels = None
depends_on = None

POLICY = "stored_file_hide_trash"
RESTRICTED_ROLES = ("hocx_abgabebox", "hocx_photo_worker")


def _existing_roles() -> list[str]:
    rows = op.get_bind().exec_driver_sql(
        "SELECT rolname FROM pg_roles WHERE rolname IN ('hocx_abgabebox', 'hocx_photo_worker') ORDER BY rolname"
    )
    return [row[0] for row in rows]


def upgrade() -> None:
    op.add_column("stored_file", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "stored_file",
        sa.Column("deleted_by", sa.BigInteger(), sa.ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index(
        "idx_stored_file_trash",
        "stored_file",
        ["tenant_id", "deleted_at"],
        postgresql_where=sa.text("deleted_at IS NOT NULL"),
    )
    roles = _existing_roles()
    if roles:
        op.execute(
            f"CREATE POLICY {POLICY} ON public.stored_file AS RESTRICTIVE FOR ALL TO {', '.join(roles)} "  # sql-ok: feste Bezeichner
            "USING (deleted_at IS NULL) WITH CHECK (deleted_at IS NULL)"
        )


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON public.stored_file")  # sql-ok: feste Bezeichner
    op.drop_index("idx_stored_file_trash", table_name="stored_file")
    op.drop_column("stored_file", "deleted_by")
    op.drop_column("stored_file", "deleted_at")
