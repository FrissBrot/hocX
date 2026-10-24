"""Ähnliche Fotos und Duplikate serverseitig vorberechnet.

Die Tabs "Duplikate" und "Ähnliche" rechneten bisher im Request: bis 1500 Bilder paarweise
vergleichen und für jedes Kandidatenpaar beide Originale laden - bei kaltem Cache länger als der
Browser wartete ("Ähnliche Fotos konnten nicht geladen werden"). Jetzt gruppiert der job-worker
(photo_similarity_refresh) je Mandant und Art im Hintergrund und legt das Ergebnis hier ab; der
Browser ruft es nur noch ab, wie Alben.

`groups` enthält nur Gruppen mit mindestens zwei Bildern als Listen von public_ids. Beim Abruf
wird gegen die aktuellen Bilder gefiltert (gelöschte fallen sofort heraus) und die beste Aufnahme
nach den aktuellen Qualitätswerten bestimmt. `fingerprint` beschreibt die gruppierte Bildmenge;
ändert sie sich, rechnet der Job neu.

RLS wie die übrigen Mandantentabellen.

Revision ID: 0152_photo_similarity_result
Revises: 0151_overload_priority
Create Date: 2026-10-24
"""

from alembic import op

revision = "0152_photo_similarity_result"
down_revision = "0151_overload_priority"
branch_labels = None
depends_on = None

SCOPE = "(SELECT public.hocx_rls_tenant())"
BASE = f"({SCOPE} IS NULL OR tenant_id = {SCOPE})"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE photo_similarity_result (
            tenant_id bigint NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            kind text NOT NULL,
            status text NOT NULL DEFAULT 'ready',
            fingerprint text NOT NULL,
            image_count integer NOT NULL DEFAULT 0,
            groups jsonb NOT NULL DEFAULT '[]'::jsonb,
            computed_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, kind),
            CONSTRAINT ck_photo_similarity_result_kind CHECK (kind IN ('duplicate', 'series')),
            CONSTRAINT ck_photo_similarity_result_status CHECK (status IN ('ready', 'incomplete', 'too_many'))
        )
        """
    )
    op.execute(f"CREATE POLICY tenant_isolation ON public.photo_similarity_result FOR ALL USING {BASE} WITH CHECK {BASE}")  # sql-ok: feste Policy-Ausdrücke
    op.execute("ALTER TABLE public.photo_similarity_result ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS photo_similarity_result")
