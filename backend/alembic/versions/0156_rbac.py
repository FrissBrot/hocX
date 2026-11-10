"""Rollen und Berechtigungen je Mandant (RBAC).

Ersetzt die feste Rolle pro Konto (app_user.role_id -> globale Tabelle role) durch
mandanteneigene Rollen mit systemseitig definierten Berechtigungen. Hintergrund und
Entscheidungen: docs/RBAC_ARCHITECTURE_PROPOSAL.md.

- ``permission``: Lookup der Permission-Keys (Quelle: permissions/catalog.json). Nur per
  Migration gepflegt, hocx_app darf nur lesen.
- ``tenant_role``: Rollen eines Mandanten. ``system_key`` markiert die vier Standardrollen, die
  die bisherigen festen Rollen exakt abbilden. Standardrollen haben keinen Namen (``name`` NULL):
  die Oberfläche übersetzt sie, bis der Mandant sie umbenennt.
- ``tenant_role_permission``: Rolle -> Permission. Die Standardrolle ``admin`` hat keine Zeilen,
  sie bekommt beim Laden immer alle Permissions (core/permissions.py).
- ``user_role``: Konto -> Rolle (mehrere je Konto). Zusammengesetzte Fremdschlüssel über
  (tenant_id, …) verhindern schon in der Datenbank, dass ein Konto eine Rolle eines anderen
  Mandanten bekommt.

Jeder bestehende und jeder neue Mandant bekommt die vier Standardrollen
(``hocx_seed_tenant_roles``, Trigger auf ``tenant``). Jedes Konto bekommt die Standardrolle,
die seiner bisherigen Rolle entspricht - kein Konto gewinnt oder verliert ein Recht.
``app_user.role_id`` und ``role`` entfernt erst 0157.

Revision ID: 0156_rbac
Revises: 0155_element_library
Create Date: 2026-10-26
"""

from alembic import op

revision = "0156_rbac"
down_revision = "0155_element_library"
branch_labels = None
depends_on = None

SCOPE = "(SELECT public.hocx_rls_tenant())"
BASE = f"({SCOPE} IS NULL OR tenant_id = {SCOPE})"
UNSCOPED = f"{SCOPE} IS NULL"

# Eingefrorener Stand von permissions/catalog.json zum Zeitpunkt dieser Revision. Spätere
# Permissions ergänzt jeweils die Migration, die sie einführt (Tabelle permission + Funktion
# hocx_seed_tenant_roles + bestehende Standardrollen).
PERMISSIONS = (
    "meetings.read",
    "meetings.read_drafts",
    "meetings.edit",
    "templates.edit",
    "templates.manage",
    "participants.manage",
    "finances.read",
    "finances.manage",
    "reports.personal",
    "files.manage",
    "submissions.read",
    "submissions.manage",
    "settings.manage",
    "access.manage",
    "data.export",
)
SYSTEM_ROLE_PERMISSIONS = {
    "writer": (
        "meetings.read", "meetings.read_drafts", "meetings.edit", "templates.edit", "participants.manage",
        "finances.read", "reports.personal", "files.manage", "submissions.read", "submissions.manage",
    ),
    "kassier": ("meetings.read", "meetings.read_drafts", "finances.read", "finances.manage", "reports.personal", "submissions.read"),
    "reader": ("meetings.read", "finances.read", "submissions.read"),
}


def _quote(value: str) -> str:
    # Nur feste Literale aus dieser Datei (keine Benutzereingaben).
    return "'" + value.replace("'", "''") + "'"


def upgrade() -> None:
    op.execute("CREATE TABLE permission (key text PRIMARY KEY, CONSTRAINT ck_permission_key CHECK (key ~ '^[a-z_]+\\.[a-z_]+$'))")
    values = ", ".join(f"({_quote(key)})" for key in PERMISSIONS)
    op.execute(f"INSERT INTO permission (key) VALUES {values}")  # sql-ok: feste Literale aus dieser Migration
    op.execute("REVOKE INSERT, UPDATE, DELETE ON permission FROM hocx_app")

    op.execute(
        """
        CREATE TABLE tenant_role (
            id bigserial PRIMARY KEY,
            public_id uuid NOT NULL DEFAULT uuidv7() UNIQUE,
            tenant_id bigint NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            name text,
            description text,
            system_key text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_tenant_role_tenant_id UNIQUE (tenant_id, id),
            CONSTRAINT ck_tenant_role_system_key CHECK (system_key IN ('admin', 'writer', 'kassier', 'reader')),
            CONSTRAINT ck_tenant_role_name CHECK (
                (name IS NULL AND system_key IS NOT NULL) OR length(btrim(name)) > 0
            )
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX uq_tenant_role_name ON tenant_role (tenant_id, lower(name)) WHERE name IS NOT NULL")
    op.execute("CREATE UNIQUE INDEX uq_tenant_role_system_key ON tenant_role (tenant_id, system_key) WHERE system_key IS NOT NULL")
    op.execute(
        "CREATE TRIGGER trg_tenant_role_updated_at BEFORE UPDATE ON public.tenant_role "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )

    op.execute(
        """
        CREATE TABLE tenant_role_permission (
            role_id bigint NOT NULL REFERENCES tenant_role(id) ON DELETE CASCADE,
            permission_key text NOT NULL REFERENCES permission(key) ON DELETE CASCADE,
            PRIMARY KEY (role_id, permission_key)
        )
        """
    )
    op.execute("CREATE INDEX idx_tenant_role_permission_key ON tenant_role_permission (permission_key)")

    op.execute("ALTER TABLE app_user ADD CONSTRAINT uq_app_user_tenant_id UNIQUE (tenant_id, id)")
    op.execute(
        """
        CREATE TABLE user_role (
            tenant_id bigint NOT NULL,
            user_id bigint NOT NULL,
            role_id bigint NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, role_id),
            CONSTRAINT fk_user_role_user FOREIGN KEY (tenant_id, user_id)
                REFERENCES app_user (tenant_id, id) ON DELETE CASCADE,
            CONSTRAINT fk_user_role_role FOREIGN KEY (tenant_id, role_id)
                REFERENCES tenant_role (tenant_id, id) ON DELETE RESTRICT
        )
        """
    )
    op.execute("CREATE INDEX idx_user_role_role ON user_role (role_id)")
    op.execute("CREATE INDEX idx_user_role_tenant ON user_role (tenant_id)")

    for table in ("tenant_role", "user_role"):
        op.execute(f"CREATE POLICY tenant_isolation ON public.{table} FOR ALL USING {BASE} WITH CHECK {BASE}")  # sql-ok: feste Bezeichner und Policy-Ausdrücke
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")  # sql-ok: fester Tabellenname
    parent = f"({UNSCOPED} OR EXISTS (SELECT 1 FROM public.tenant_role p WHERE p.id = tenant_role_permission.role_id))"
    op.execute(
        f"CREATE POLICY tenant_isolation ON public.tenant_role_permission FOR ALL TO hocx_app USING {parent} WITH CHECK {parent}"  # sql-ok: feste Policy-Ausdrücke
    )
    op.execute("ALTER TABLE public.tenant_role_permission ENABLE ROW LEVEL SECURITY")

    pairs = ", ".join(
        f"({_quote(system_key)}, {_quote(key)})" for system_key, keys in SYSTEM_ROLE_PERMISSIONS.items() for key in keys
    )
    op.execute(
        f"""
        CREATE FUNCTION public.hocx_seed_tenant_roles(p_tenant_id bigint) RETURNS void
            LANGUAGE plpgsql
            SET search_path = public
        AS $$
        BEGIN
            INSERT INTO tenant_role (tenant_id, system_key)
            SELECT p_tenant_id, k FROM unnest(ARRAY['admin', 'writer', 'kassier', 'reader']) AS k
            ON CONFLICT DO NOTHING;
            INSERT INTO tenant_role_permission (role_id, permission_key)
            SELECT r.id, v.permission_key
              FROM tenant_role r
              JOIN (VALUES {pairs}) AS v(system_key, permission_key) ON v.system_key = r.system_key
             WHERE r.tenant_id = p_tenant_id
            ON CONFLICT DO NOTHING;
        END
        $$
        """  # sql-ok: feste Literale aus dieser Migration
    )
    op.execute(
        """
        CREATE FUNCTION public.hocx_tenant_seed_roles_trigger() RETURNS trigger
            LANGUAGE plpgsql
            SET search_path = public
        AS $$
        BEGIN
            PERFORM public.hocx_seed_tenant_roles(NEW.id);
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_tenant_seed_roles AFTER INSERT ON public.tenant "
        "FOR EACH ROW EXECUTE FUNCTION public.hocx_tenant_seed_roles_trigger()"
    )

    # Bestand: Standardrollen für alle Mandanten, dann jedes Konto auf die Standardrolle seiner
    # bisherigen Rolle.
    op.execute("SELECT public.hocx_seed_tenant_roles(id) FROM tenant")
    op.execute(
        """
        INSERT INTO user_role (tenant_id, user_id, role_id)
        SELECT u.tenant_id, u.id, tr.id
          FROM app_user u
          JOIN role r ON r.id = u.role_id
          JOIN tenant_role tr ON tr.tenant_id = u.tenant_id AND tr.system_key = r.code
        """
    )
    op.execute(
        """
        DO $$
        DECLARE
            missing bigint;
        BEGIN
            SELECT count(*) INTO missing
              FROM app_user u
             WHERE NOT EXISTS (SELECT 1 FROM user_role ur WHERE ur.user_id = u.id);
            IF missing > 0 THEN
                RAISE EXCEPTION 'RBAC-Migration: % Konten ohne Standardrolle (unbekannter role.code?)', missing;
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_tenant_seed_roles ON public.tenant")
    op.execute("DROP FUNCTION IF EXISTS public.hocx_tenant_seed_roles_trigger()")
    op.execute("DROP FUNCTION IF EXISTS public.hocx_seed_tenant_roles(bigint)")
    op.execute("DROP TABLE IF EXISTS user_role")
    op.execute("ALTER TABLE app_user DROP CONSTRAINT IF EXISTS uq_app_user_tenant_id")
    op.execute("DROP TABLE IF EXISTS tenant_role_permission")
    op.execute("DROP TABLE IF EXISTS tenant_role")
    op.execute("DROP TABLE IF EXISTS permission")
