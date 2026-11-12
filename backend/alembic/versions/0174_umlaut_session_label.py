"""Umlaute: gespeicherte Vorgabe «Naechste Sitzung» wird «Nächste Sitzung».

Der Titel des Sitzungsdatum-Blocks (session_label) wurde mit der Ersatzschreibung «Naechste
Sitzung» als Vorgabe gespeichert und erscheint so im Editor und im PDF. Korrigiert werden Vorlagen
(element_definition, template_element) und Protokolle, die noch nicht abgeschlossen sind;
abgeschlossene Protokolle bleiben unverändert (fixierter Stand, siehe Freeze-Schutz).
Ersetzt wird nur der exakte JSON-Wert "Naechste Sitzung". Kein Downgrade (Text bleibt korrigiert).

Revision ID: 0174_umlaut_session_label
Revises: 0173_submission_keep_open
Create Date: 2026-11-12
"""

from alembic import op

revision = "0174_umlaut_session_label"
down_revision = "0173_submission_keep_open"
branch_labels = None
depends_on = None

OLD = '"Naechste Sitzung"'
NEW = '"Nächste Sitzung"'


def upgrade() -> None:
    for table in ("element_definition", "template_element"):
        op.execute(
            f"UPDATE {table} SET configuration_json = replace(configuration_json::text, '{OLD}', '{NEW}')::jsonb "  # sql-ok: feste Tabellennamen und Texte
            f"WHERE configuration_json::text LIKE '%{OLD}%'"
        )
    op.execute(
        f"""
        UPDATE protocol_element_block b
           SET configuration_snapshot_json = replace(b.configuration_snapshot_json::text, '{OLD}', '{NEW}')::jsonb
          FROM protocol_element e
          JOIN protocol p ON p.id = e.protocol_id
         WHERE b.protocol_element_id = e.id
           AND p.status <> 'abgeschlossen'
           AND b.configuration_snapshot_json::text LIKE '%{OLD}%'
        """  # sql-ok: feste Texte, keine Eingaben
    )


def downgrade() -> None:
    pass
