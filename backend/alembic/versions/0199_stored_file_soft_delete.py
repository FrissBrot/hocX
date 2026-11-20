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

Abgabebox-Kapazität: Die SECURITY-DEFINER-Funktionen ``submission_linked_file_counts`` und
``submission_withdrawn_elements`` (zuletzt 0198) laufen als Eigentümer, die RESTRICTIVE-Policy greift
dort nicht. Sie bekommen deshalb einen eigenen Filter: eine verknüpfte Galerie-Datei im Papierkorb
belegt keinen Platz im Element (wie ``submission_upload_rules`` im Backend) und sperrt es auch nicht
als «zurückgezogen». Rückgabespalten, Rechte und ``search_path`` bleiben wie in 0198; der Downgrade
legt die 0198-Fassung wieder an.

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
ABGABEBOX = "hocx_abgabebox"
RESTRICTED_ROLES = ("hocx_abgabebox", "hocx_photo_worker")


def _existing_roles() -> list[str]:
    rows = op.get_bind().exec_driver_sql(
        "SELECT rolname FROM pg_roles WHERE rolname IN ('hocx_abgabebox', 'hocx_photo_worker') ORDER BY rolname"
    )
    return [row[0] for row in rows]


# Galerie-Datei im Papierkorb: zählt für die Abgabebox nicht (Platzhalter in den Funktionen unten).
_GALLERY_NOT_TRASHED = (
    "AND NOT EXISTS (SELECT 1 FROM stored_file s WHERE s.id = g.stored_file_id AND s.deleted_at IS NOT NULL)"
)


def _counts(trash_filter: str) -> str:
    return f"""
CREATE FUNCTION public.submission_linked_file_counts(p_assignment_id BIGINT)
RETURNS TABLE (event_id BIGINT, list_entry_id BIGINT, manual_element_id BIGINT, file_count INTEGER)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
    AS $$
        SELECT e.id, le.id, m.id, COUNT(*)::INTEGER
        FROM gallery_image g
        JOIN submission_assignment a ON a.id = g.submission_assignment_id AND a.tenant_id = g.tenant_id
        LEFT JOIN event e
          ON g.submission_element_ref = 'event-' || e.public_id::TEXT AND e.tenant_id = a.tenant_id
        LEFT JOIN list_entry le
          ON g.submission_element_ref = 'entry-' || le.public_id::TEXT AND le.list_definition_id = a.list_definition_id
        LEFT JOIN submission_manual_element m
          ON g.submission_element_ref = 'manual-' || m.public_id::TEXT AND m.assignment_id = a.id AND NOT m.is_default
        WHERE g.submission_assignment_id = p_assignment_id
          AND g.submission_withdrawn_at IS NULL
          {trash_filter}
          -- nur der Mandant des gesetzten Upload-Links (wie die RLS der Abgabebox, 0133)
          AND a.tenant_id = (SELECT public.hocx_rls_abgabebox_tenant())
          AND (e.id IS NOT NULL OR le.id IS NOT NULL OR m.id IS NOT NULL OR g.submission_element_ref = 'manual')
        GROUP BY e.id, le.id, m.id
    $$;
"""  # sql-ok: nur fester Filter-Baustein aus diesem Modul


def _withdrawn(trash_filter: str) -> str:
    return f"""
CREATE FUNCTION public.submission_withdrawn_elements(p_assignment_id BIGINT)
RETURNS TABLE (event_id BIGINT, list_entry_id BIGINT, manual_element_id BIGINT)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
    AS $$
        SELECT DISTINCT u.event_id, u.list_entry_id, u.manual_element_id
        FROM submission_upload_file f
        JOIN submission_upload u ON u.id = f.upload_id
        JOIN submission_assignment a ON a.id = u.assignment_id
        WHERE u.assignment_id = p_assignment_id
          AND f.withdrawn_at IS NOT NULL
          AND a.tenant_id = (SELECT public.hocx_rls_abgabebox_tenant())
        UNION
        SELECT e.id, le.id, m.id
        FROM gallery_image g
        JOIN submission_assignment a ON a.id = g.submission_assignment_id AND a.tenant_id = g.tenant_id
        LEFT JOIN event e
          ON g.submission_element_ref = 'event-' || e.public_id::TEXT AND e.tenant_id = a.tenant_id
        LEFT JOIN list_entry le
          ON g.submission_element_ref = 'entry-' || le.public_id::TEXT AND le.list_definition_id = a.list_definition_id
        LEFT JOIN submission_manual_element m
          ON g.submission_element_ref = 'manual-' || m.public_id::TEXT AND m.assignment_id = a.id AND NOT m.is_default
        WHERE g.submission_assignment_id = p_assignment_id
          AND g.submission_withdrawn_at IS NOT NULL
          {trash_filter}
          AND a.tenant_id = (SELECT public.hocx_rls_abgabebox_tenant())
          AND (e.id IS NOT NULL OR le.id IS NOT NULL OR m.id IS NOT NULL OR g.submission_element_ref = 'manual')
    $$;
"""  # sql-ok: nur fester Filter-Baustein aus diesem Modul


def _replace_abgabebox_functions(trash_filter: str) -> None:
    """Wie 0198: neu anlegen, PUBLIC entziehen, nur die Abgabebox-Rolle darf ausführen."""
    op.execute("DROP FUNCTION IF EXISTS public.submission_linked_file_counts(BIGINT)")
    op.execute("DROP FUNCTION IF EXISTS public.submission_withdrawn_elements(BIGINT)")
    op.execute(_counts(trash_filter))
    op.execute(_withdrawn(trash_filter))
    for function in ("submission_linked_file_counts", "submission_withdrawn_elements"):
        op.execute(f"REVOKE ALL ON FUNCTION public.{function}(BIGINT) FROM PUBLIC")  # sql-ok: feste Funktionsnamen
        op.execute(f"GRANT EXECUTE ON FUNCTION public.{function}(BIGINT) TO {ABGABEBOX}")  # sql-ok: feste Funktionsnamen


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
    _replace_abgabebox_functions(_GALLERY_NOT_TRASHED)


def downgrade() -> None:
    # 0198-Fassung (ohne Papierkorb-Filter), bevor die Spalte wegfällt
    _replace_abgabebox_functions("")
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON public.stored_file")  # sql-ok: feste Bezeichner
    op.drop_index("idx_stored_file_trash", table_name="stored_file")
    op.drop_column("stored_file", "deleted_by")
    op.drop_column("stored_file", "deleted_at")
