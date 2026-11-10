"""Anliegen: Punkte für kommende Sitzungen.

Ein Traktandum gehört zu einer Protokollvorlage und einem ihrer Punkte (template_element). Es
wartet (protocol_id NULL), bis es im nächsten passenden Protokoll erscheint: dem frühesten
Protokoll der Vorlage im Status geplant/vorbereitet mit Datum ab `earliest_date`. Sobald dieses
Protokoll durchgeführt wird, bindet es das Traktandum fest (protocol_id, protocol_element_id).
Im Editor erstellte Traktanden sind sofort an ihr Protokoll gebunden.

`schedule_kind` hält nur fest, wie der Termin gewählt wurde ("nächste Sitzung" oder Monat
`scheduled_month`); massgebend für die Auswahl ist `earliest_date`. Vertagen löst die Bindung
und setzt ein neues `earliest_date` (bei "nächste Sitzung" nach dem bisherigen Protokoll).

`user_agenda_template_preference` merkt sich die zuletzt im Erstell-Popup gewählte Vorlage.

RLS wie die übrigen Mandantentabellen.

Revision ID: 0153_agenda_item
Revises: 0152_photo_similarity_result
Create Date: 2026-10-24
"""

from alembic import op

revision = "0153_agenda_item"
down_revision = "0152_photo_similarity_result"
branch_labels = None
depends_on = None

SCOPE = "(SELECT public.hocx_rls_tenant())"
BASE = f"({SCOPE} IS NULL OR tenant_id = {SCOPE})"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE agenda_item (
            id bigserial PRIMARY KEY,
            public_id uuid NOT NULL DEFAULT uuidv7() UNIQUE,
            tenant_id bigint NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            template_id bigint NOT NULL REFERENCES template(id) ON DELETE CASCADE,
            template_element_id bigint REFERENCES template_element(id) ON DELETE SET NULL,
            protocol_id bigint REFERENCES protocol(id) ON DELETE SET NULL,
            protocol_element_id bigint REFERENCES protocol_element(id) ON DELETE SET NULL,
            title text NOT NULL,
            body text,
            schedule_kind text NOT NULL DEFAULT 'next_meeting',
            scheduled_month date,
            earliest_date date NOT NULL,
            postponed_count integer NOT NULL DEFAULT 0,
            created_by bigint REFERENCES app_user(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_agenda_item_schedule_kind CHECK (schedule_kind IN ('next_meeting', 'month')),
            CONSTRAINT ck_agenda_item_scheduled_month CHECK (
                (schedule_kind = 'month') = (scheduled_month IS NOT NULL)
            ),
            CONSTRAINT ck_agenda_item_postponed_count CHECK (postponed_count >= 0),
            CONSTRAINT ck_agenda_item_title CHECK (length(btrim(title)) > 0)
        )
        """
    )
    op.execute("CREATE INDEX idx_agenda_item_tenant ON agenda_item (tenant_id)")
    op.execute(
        "CREATE INDEX idx_agenda_item_pending ON agenda_item (template_id, earliest_date) WHERE protocol_id IS NULL"
    )
    op.execute("CREATE INDEX idx_agenda_item_protocol ON agenda_item (protocol_id)")
    op.execute("CREATE INDEX idx_agenda_item_protocol_element ON agenda_item (protocol_element_id)")
    op.execute("CREATE INDEX idx_agenda_item_template_element ON agenda_item (template_element_id)")
    op.execute("CREATE INDEX idx_agenda_item_created_by ON agenda_item (created_by)")
    op.execute(
        "CREATE TRIGGER trg_agenda_item_updated_at BEFORE UPDATE ON public.agenda_item "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )
    op.execute(
        """
        CREATE TABLE user_agenda_template_preference (
            user_id bigint NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
            tenant_id bigint NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            template_id bigint REFERENCES template(id) ON DELETE SET NULL,
            PRIMARY KEY (user_id, tenant_id)
        )
        """
    )
    for table in ("agenda_item", "user_agenda_template_preference"):
        op.execute(f"CREATE POLICY tenant_isolation ON public.{table} FOR ALL USING {BASE} WITH CHECK {BASE}")  # sql-ok: feste Bezeichner und Policy-Ausdrücke
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")  # sql-ok: fester Tabellenname


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_agenda_template_preference")
    op.execute("DROP TABLE IF EXISTS agenda_item")
