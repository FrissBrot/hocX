"""Admin-Redesign Phase D: Kennzahlen-Verlauf für Dashboard und Analysen.

- ``platform_metric_daily``: plattformweite Tageswerte (Summen/Zählungen, keine Mandanten- und
  keine Personendaten), geschrieben vom Job ``metrics_rollup``. ``dimension`` unterscheidet z. B.
  den Feature-Code bei ``feature.booked``.
- ``tenant_metric_daily``: Tageswerte je Mandant (Speicher, aktive Benutzer, Anmeldungen,
  Nutzung je Modul) - nur Zählwerte. Mandantendaten: ``tenant_id NOT NULL`` + RLS im selben
  Change (SECURITY-RULES §2.1). Die Plattform liest sie ohne gebundenen Mandanten.
- ``system_metric_sample``: Ressourcen-Stichproben des ``system_monitor`` (alle ~5 min),
  Aufbewahrung 14 Tage über ``log_cleanup``. Plattformweit, ohne Mandantenbezug.
  (``system_error_log(created_at)`` hat bereits ``idx_system_error_log_created``.)
"""
from __future__ import annotations

from alembic import op

revision = "0208_platform_metrics"
down_revision = "0207_security_read"
branch_labels = None
depends_on = None

SCOPE = "(SELECT public.hocx_rls_tenant())"
BASE = f"({SCOPE} IS NULL OR tenant_id = {SCOPE})"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE platform_metric_daily (
            day date NOT NULL,
            metric text NOT NULL,
            dimension text NOT NULL DEFAULT '',
            value numeric NOT NULL,
            computed_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (day, metric, dimension)
        )
        """
    )
    op.execute("CREATE INDEX idx_platform_metric_daily_metric_day ON platform_metric_daily (metric, day)")
    op.execute(
        """
        CREATE TABLE tenant_metric_daily (
            tenant_id bigint NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            day date NOT NULL,
            metric text NOT NULL,
            value numeric NOT NULL,
            computed_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, day, metric)
        )
        """
    )
    op.execute("CREATE INDEX idx_tenant_metric_daily_metric_day ON tenant_metric_daily (metric, day)")
    op.execute(f"CREATE POLICY tenant_isolation ON public.tenant_metric_daily FOR ALL USING {BASE} WITH CHECK {BASE}")  # sql-ok: feste Bezeichner und Policy-Ausdrücke
    op.execute("ALTER TABLE public.tenant_metric_daily ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE TABLE system_metric_sample (
            id bigserial PRIMARY KEY,
            ts timestamptz NOT NULL DEFAULT now(),
            metric text NOT NULL,
            subject text NOT NULL DEFAULT '',
            value double precision NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX idx_system_metric_sample_ts ON system_metric_sample (ts)")
    op.execute("CREATE INDEX idx_system_metric_sample_metric_ts ON system_metric_sample (metric, ts)")
    for table in ("platform_metric_daily", "tenant_metric_daily", "system_metric_sample"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.{table} TO hocx_app")  # sql-ok: feste Tabellennamen
    op.execute("GRANT SELECT, USAGE ON SEQUENCE public.system_metric_sample_id_seq TO hocx_app")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS system_metric_sample")
    op.execute("DROP TABLE IF EXISTS tenant_metric_daily")
    op.execute("DROP TABLE IF EXISTS platform_metric_daily")
