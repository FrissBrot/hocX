"""Feature-Entitlements: Nur-Lesen-Zustand, Herkunft und vier neue buchbare Features.

- tenant_feature.access: 'full' (gebucht) oder 'read_only' (nach Downgrade: Daten lesbar,
  Änderungen gesperrt; Verhalten je Feature in permissions/features.json).
- tenant_feature.source: 'plan' (kommt aus dem Plan des Mandanten, folgt Planwechseln) oder
  'addon' (einzeln gebucht oder Bestandsschutz, bleibt bei Planwechseln). Backfill: Features im
  aktuellen Plan des Mandanten gelten als 'plan', alle übrigen als 'addon'.
- Neue Features task_packages, custom_roles, photo_sharing, document_designer. Bisher für alle
  Mandanten frei verfügbar: jeder bestehende Mandant bekommt sie als 'addon' (Bestandsschutz,
  niemand verliert still Funktionen - Muster aus 0084/0085).
- Plan-Zuordnung (Seeds, im Adminportal änderbar): starter ohne die neuen Features, standard mit
  task_packages, photo_sharing, document_designer, premium zusätzlich custom_roles
  (docs/SAAS_SUBSCRIPTION_STRATEGY.md).

Revision ID: 0158_feature_entitlements
Revises: 0157_drop_legacy_role
Create Date: 2026-10-27
"""

from alembic import op

revision = "0158_feature_entitlements"
down_revision = "0157_drop_legacy_role"
branch_labels = None
depends_on = None

ABGABEBOX_ROLE = "hocx_abgabebox"
NEW_FEATURES = (
    ("task_packages", "Aufgabenpakete", "Wiederkehrende Aufgaben je Zyklus automatisch als Pendenzen erzeugen"),
    ("custom_roles", "Eigene Rollen", "Eigene Rollen anlegen und die Rechte der Standardrollen anpassen"),
    ("photo_sharing", "Teilen von Fotos", "Öffentliche Freigabelinks und mit Partnervereinen geteilte Alben"),
    ("document_designer", "Dokument-Designer", "Eigene Dokumentvorlagen und Bausteine im Document Studio gestalten"),
)
PLAN_FEATURES = {
    "standard": ("task_packages", "photo_sharing", "document_designer"),
    "premium": ("task_packages", "photo_sharing", "document_designer", "custom_roles"),
}


def upgrade() -> None:
    op.execute("ALTER TABLE tenant_feature ADD COLUMN access text NOT NULL DEFAULT 'full'")
    op.execute("ALTER TABLE tenant_feature ADD CONSTRAINT ck_tenant_feature_access CHECK (access IN ('full', 'read_only'))")
    op.execute("ALTER TABLE tenant_feature ADD COLUMN source text NOT NULL DEFAULT 'addon'")
    op.execute("ALTER TABLE tenant_feature ADD CONSTRAINT ck_tenant_feature_source CHECK (source IN ('plan', 'addon'))")
    # Die Abgabebox prüft das Feature selbst (nur volle Buchung nimmt Uploads an)
    op.execute(f"GRANT SELECT (access) ON TABLE tenant_feature TO {ABGABEBOX_ROLE}")  # sql-ok: fester Rollenname
    op.execute(
        """
        UPDATE tenant_feature tf SET source = 'plan'
        FROM tenant t
        JOIN plan_feature pf ON pf.plan_code = t.plan_code
        WHERE t.id = tf.tenant_id AND pf.feature_code = tf.feature_code
        """
    )
    for code, name, description in NEW_FEATURES:
        op.execute(
            f"INSERT INTO feature (code, name, description) VALUES ('{code}', '{name}', '{description}') "  # sql-ok: feste Werte aus dieser Migration
            "ON CONFLICT (code) DO NOTHING"
        )
        op.execute(
            "INSERT INTO tenant_feature (tenant_id, feature_code, source) "
            f"SELECT id, '{code}', 'addon' FROM tenant "  # sql-ok: fester Feature-Code aus dieser Migration
            "ON CONFLICT (tenant_id, feature_code) DO NOTHING"
        )
    for plan_code, codes in PLAN_FEATURES.items():
        for code in codes:
            op.execute(
                "INSERT INTO plan_feature (plan_code, feature_code) "
                f"SELECT '{plan_code}', '{code}' WHERE EXISTS (SELECT 1 FROM plan WHERE code = '{plan_code}') "  # sql-ok: feste Codes aus dieser Migration
                "ON CONFLICT DO NOTHING"
            )


def downgrade() -> None:
    codes = ", ".join(f"'{code}'" for code, _, _ in NEW_FEATURES)
    op.execute(f"DELETE FROM plan_feature WHERE feature_code IN ({codes})")  # sql-ok: feste Codes aus dieser Migration
    op.execute(f"DELETE FROM tenant_feature WHERE feature_code IN ({codes})")  # sql-ok: feste Codes aus dieser Migration
    op.execute(f"DELETE FROM feature WHERE code IN ({codes})")  # sql-ok: feste Codes aus dieser Migration
    # Nur-Lesen-Zeilen waren vorher nicht gebucht
    op.execute("DELETE FROM tenant_feature WHERE access = 'read_only'")
    op.execute("ALTER TABLE tenant_feature DROP CONSTRAINT ck_tenant_feature_source")
    op.execute("ALTER TABLE tenant_feature DROP COLUMN source")
    op.execute(f"REVOKE SELECT (access) ON TABLE tenant_feature FROM {ABGABEBOX_ROLE}")  # sql-ok: fester Rollenname
    op.execute("ALTER TABLE tenant_feature DROP CONSTRAINT ck_tenant_feature_access")
    op.execute("ALTER TABLE tenant_feature DROP COLUMN access")
