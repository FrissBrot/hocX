"""Bussen für zu spät erledigte Pendenzen (Todos).

- `fine_tariff_group`: Tarife eines Mandanten (z. B. Lernende, Nicht-Verdiener, Vollverdiener).
  Genau ein Tarif kann Standard sein; er gilt für Personen ohne eigenen Tarif.
  `app_user.fine_tariff_group_id` trägt den Tarif einer Person (Profil).
- `todo_fine_rule`: Regel mit Filter (Tags, Aufgabenpakete, Verantwortliche, Rollen), Intervall
  ("pro N Tage"), Aufteilung bei mehreren Verantwortlichen und Gültigkeitsbeginn. Die Filter
  liegen in drei Untertabellen, die Beträge je Tarif in `todo_fine_rule_rate`.
- `protocol_todo.fine_*`: Busse am Todo von Hand: automatisch (Regeln), feste Regel, fixer Betrag
  oder keine Busse.
- `todo_fine`: beim Erledigen eingefrorene Busse je Person. Solange ein Todo offen ist, rechnet
  der Server die laufende Busse jedes Mal neu (nicht gespeichert).

Eigenes buchbares Feature `todo_fines` (Modul Finanzen, braucht `finance`): neu und darum für
keinen bestehenden Mandanten und keinen Plan vorgegeben - die Plattform-Administration schaltet
es je Mandant im Feature-Tab ein oder aus. Ausgeschaltet bleiben die Daten lesbar (read_only),
es entstehen aber keine neuen Bussen.

Untertabellen ohne eigene tenant_id bekommen die RLS-Policy über ihre Elterntabelle
(wie 0134_child_table_rls).

Revision ID: 0169_todo_fines
Revises: 0168_s3_only
Create Date: 2026-11-11
"""

from alembic import op

revision = "0169_todo_fines"
down_revision = "0168_s3_only"
branch_labels = None
depends_on = None

SCOPE = "(SELECT public.hocx_rls_tenant())"
BASE = f"({SCOPE} IS NULL OR tenant_id = {SCOPE})"
ROLES = "hocx_app, hocx_photo_worker"
UNSCOPED = f"{SCOPE} IS NULL"

TENANT_TABLES = ("fine_tariff_group", "todo_fine_rule", "todo_fine")
# Tabelle -> (Elterntabelle, Spalte)
CHILD_TABLES = {
    "todo_fine_rule_rate": ("todo_fine_rule", "rule_id"),
    "todo_fine_rule_task_package": ("todo_fine_rule", "rule_id"),
    "todo_fine_rule_participant": ("todo_fine_rule", "rule_id"),
    "todo_fine_rule_role": ("todo_fine_rule", "rule_id"),
}


def upgrade() -> None:
    op.execute(
        "INSERT INTO feature (code, name, description) VALUES ('todo_fines', 'Pendenzen-Bussen', "
        "'Bussen für zu spät erledigte Pendenzen nach Regeln und Tarifen') ON CONFLICT (code) DO NOTHING"
    )
    op.execute(
        """
        CREATE TABLE fine_tariff_group (
            id bigserial PRIMARY KEY,
            public_id uuid NOT NULL DEFAULT uuidv7() UNIQUE,
            tenant_id bigint NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            name text NOT NULL,
            sort_index integer NOT NULL DEFAULT 0,
            is_default boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_fine_tariff_group_tenant_name UNIQUE (tenant_id, name),
            CONSTRAINT ck_fine_tariff_group_name CHECK (length(btrim(name)) > 0)
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX uq_fine_tariff_group_default ON fine_tariff_group (tenant_id) WHERE is_default")
    op.execute(
        "CREATE TRIGGER trg_fine_tariff_group_updated_at BEFORE UPDATE ON public.fine_tariff_group "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )
    op.execute("ALTER TABLE app_user ADD COLUMN fine_tariff_group_id bigint REFERENCES fine_tariff_group(id) ON DELETE SET NULL")
    op.execute("CREATE INDEX idx_app_user_fine_tariff_group ON app_user (fine_tariff_group_id)")

    op.execute(
        """
        CREATE TABLE todo_fine_rule (
            id bigserial PRIMARY KEY,
            public_id uuid NOT NULL DEFAULT uuidv7() UNIQUE,
            tenant_id bigint NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            name text NOT NULL,
            sort_index integer NOT NULL DEFAULT 0,
            is_active boolean NOT NULL DEFAULT true,
            applies_from date NOT NULL DEFAULT CURRENT_DATE,
            interval_days integer NOT NULL DEFAULT 1,
            split_mode text NOT NULL DEFAULT 'each',
            account_id bigint REFERENCES finance_account(id) ON DELETE SET NULL,
            filter_tags jsonb NOT NULL DEFAULT '[]'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_todo_fine_rule_name CHECK (length(btrim(name)) > 0),
            CONSTRAINT ck_todo_fine_rule_interval CHECK (interval_days BETWEEN 1 AND 365),
            CONSTRAINT ck_todo_fine_rule_split_mode CHECK (split_mode IN ('each', 'split')),
            CONSTRAINT ck_todo_fine_rule_tags CHECK (jsonb_typeof(filter_tags) = 'array')
        )
        """
    )
    op.execute("CREATE INDEX idx_todo_fine_rule_tenant ON todo_fine_rule (tenant_id, sort_index)")
    op.execute("CREATE INDEX idx_todo_fine_rule_account ON todo_fine_rule (account_id)")
    op.execute(
        "CREATE TRIGGER trg_todo_fine_rule_updated_at BEFORE UPDATE ON public.todo_fine_rule "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )
    op.execute(
        """
        CREATE TABLE todo_fine_rule_rate (
            rule_id bigint NOT NULL REFERENCES todo_fine_rule(id) ON DELETE CASCADE,
            tariff_group_id bigint NOT NULL REFERENCES fine_tariff_group(id) ON DELETE CASCADE,
            base_amount numeric(15, 2) NOT NULL DEFAULT 0,
            interval_amount numeric(15, 2) NOT NULL DEFAULT 0,
            PRIMARY KEY (rule_id, tariff_group_id),
            CONSTRAINT ck_todo_fine_rule_rate_amounts CHECK (base_amount >= 0 AND interval_amount >= 0)
        )
        """
    )
    op.execute("CREATE INDEX idx_todo_fine_rule_rate_group ON todo_fine_rule_rate (tariff_group_id)")
    for table, column, target in (
        ("todo_fine_rule_task_package", "task_package_id", "task_package"),
        ("todo_fine_rule_participant", "participant_id", "app_user"),
        ("todo_fine_rule_role", "role_id", "tenant_role"),
    ):
        op.execute(
            f"""
            CREATE TABLE {table} (
                rule_id bigint NOT NULL REFERENCES todo_fine_rule(id) ON DELETE CASCADE,
                {column} bigint NOT NULL REFERENCES {target}(id) ON DELETE CASCADE,
                PRIMARY KEY (rule_id, {column})
            )
            """  # sql-ok: feste Bezeichner aus dieser Migration
        )
        op.execute(f"CREATE INDEX idx_{table}_target ON {table} ({column})")  # sql-ok: feste Bezeichner

    op.execute(
        """
        ALTER TABLE protocol_todo
            ADD COLUMN fine_mode text NOT NULL DEFAULT 'auto',
            ADD COLUMN fine_rule_id bigint REFERENCES todo_fine_rule(id) ON DELETE SET NULL,
            ADD COLUMN fine_fixed_amount numeric(15, 2),
            ADD COLUMN fine_split_mode text,
            ADD CONSTRAINT ck_protocol_todo_fine_mode CHECK (fine_mode IN ('auto', 'rule', 'fixed', 'none')),
            ADD CONSTRAINT ck_protocol_todo_fine_fixed CHECK (
                fine_mode <> 'fixed' OR (fine_fixed_amount IS NOT NULL AND fine_fixed_amount >= 0)
            ),
            ADD CONSTRAINT ck_protocol_todo_fine_split_mode CHECK (fine_split_mode IS NULL OR fine_split_mode IN ('each', 'split'))
        """
    )
    op.execute("CREATE INDEX idx_protocol_todo_fine_rule ON protocol_todo (fine_rule_id)")

    op.execute(
        """
        CREATE TABLE todo_fine (
            id bigserial PRIMARY KEY,
            public_id uuid NOT NULL DEFAULT uuidv7() UNIQUE,
            tenant_id bigint NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            protocol_todo_id bigint REFERENCES protocol_todo(id) ON DELETE SET NULL,
            rule_id bigint REFERENCES todo_fine_rule(id) ON DELETE SET NULL,
            participant_id bigint REFERENCES app_user(id) ON DELETE SET NULL,
            participant_name_snapshot text NOT NULL,
            task_snapshot text NOT NULL,
            rule_name_snapshot text,
            tariff_name_snapshot text,
            due_date date NOT NULL,
            completed_on date NOT NULL,
            days_late integer NOT NULL,
            amount numeric(15, 2) NOT NULL,
            account_id bigint REFERENCES finance_account(id) ON DELETE SET NULL,
            status text NOT NULL DEFAULT 'pending',
            collected_at timestamptz,
            collected_transaction_id bigint REFERENCES finance_transaction(id) ON DELETE SET NULL,
            collected_by_user_id bigint REFERENCES app_user(id) ON DELETE SET NULL,
            delete_comment text,
            deleted_at timestamptz,
            deleted_by_user_id bigint REFERENCES app_user(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_todo_fine_status CHECK (status IN ('pending', 'collected', 'deleted')),
            CONSTRAINT ck_todo_fine_amount CHECK (amount >= 0),
            CONSTRAINT ck_todo_fine_days_late CHECK (days_late >= 1),
            CONSTRAINT ck_todo_fine_deleted_reason CHECK (
                status <> 'deleted' OR (delete_comment IS NOT NULL AND btrim(delete_comment) <> '')
            )
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_todo_fine_todo_participant ON todo_fine (protocol_todo_id, participant_id) "
        "WHERE protocol_todo_id IS NOT NULL AND participant_id IS NOT NULL"
    )
    for column in ("tenant_id", "protocol_todo_id", "rule_id", "participant_id", "account_id",
                   "collected_transaction_id", "collected_by_user_id", "deleted_by_user_id"):
        op.execute(f"CREATE INDEX idx_todo_fine_{column} ON todo_fine ({column})")  # sql-ok: feste Spaltennamen
    op.execute(
        "CREATE TRIGGER trg_todo_fine_updated_at BEFORE UPDATE ON public.todo_fine "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )

    for table in TENANT_TABLES:
        op.execute(f"CREATE POLICY tenant_isolation ON public.{table} FOR ALL USING {BASE} WITH CHECK {BASE}")  # sql-ok: feste Bezeichner und Policy-Ausdrücke
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")  # sql-ok: fester Tabellenname
    for table, (parent, column) in CHILD_TABLES.items():
        visible = f"({UNSCOPED} OR EXISTS (SELECT 1 FROM public.{parent} p WHERE p.id = {table}.{column}))"
        op.execute(f"CREATE POLICY tenant_isolation ON public.{table} FOR ALL TO {ROLES} USING {visible} WITH CHECK {visible}")  # sql-ok: feste Bezeichner
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")  # sql-ok: fester Tabellenname


def downgrade() -> None:
    op.execute("DELETE FROM plan_feature WHERE feature_code = 'todo_fines'")
    op.execute("DELETE FROM tenant_feature WHERE feature_code = 'todo_fines'")
    op.execute("DELETE FROM feature WHERE code = 'todo_fines'")
    op.execute("DROP TABLE IF EXISTS todo_fine")
    op.execute(
        """
        ALTER TABLE protocol_todo
            DROP CONSTRAINT IF EXISTS ck_protocol_todo_fine_split_mode,
            DROP CONSTRAINT IF EXISTS ck_protocol_todo_fine_fixed,
            DROP CONSTRAINT IF EXISTS ck_protocol_todo_fine_mode,
            DROP COLUMN IF EXISTS fine_split_mode,
            DROP COLUMN IF EXISTS fine_fixed_amount,
            DROP COLUMN IF EXISTS fine_rule_id,
            DROP COLUMN IF EXISTS fine_mode
        """
    )
    for table in CHILD_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table}")  # sql-ok: feste Bezeichner
    op.execute("DROP TABLE IF EXISTS todo_fine_rule")
    op.execute("ALTER TABLE app_user DROP COLUMN IF EXISTS fine_tariff_group_id")
    op.execute("DROP TABLE IF EXISTS fine_tariff_group")
