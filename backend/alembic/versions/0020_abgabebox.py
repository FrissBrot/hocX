"""abgabebox: submission_assignment/upload/upload_file, tenant.public_slug, restricted DB role

Revision ID: 0020_abgabebox
Revises: 0019_finance_tx_cascade
Create Date: 2026-07-08
"""

import os

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0020_abgabebox"
down_revision = "0019_finance_tx_cascade"
branch_labels = None
depends_on = None

ROLE_NAME = "hocx_abgabebox"


def upgrade() -> None:
    # 1. tenant.public_slug — bestimmt die URL /{tenant_slug}/... auf der Abgabebox-Domain.
    op.add_column("tenant", sa.Column("public_slug", sa.Text(), nullable=True))
    op.create_unique_constraint("uq_tenant_public_slug", "tenant", ["public_slug"])

    # 2. submission_assignment
    op.create_table(
        "submission_assignment",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("public_slug", sa.Text(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("tag_filter", sa.Text(), nullable=True),
        sa.Column("offset_days_before", sa.Integer(), nullable=True),
        sa.Column("offset_days_after", sa.Integer(), nullable=True),
        sa.Column("list_definition_id", sa.BigInteger(), nullable=True),
        sa.Column("deadline", sa.Date(), nullable=True),
        sa.Column("allowed_file_types", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("max_files_per_element", sa.Integer(), nullable=False, server_default=sa.text("5")),
        sa.Column("max_file_size_mb", sa.Integer(), nullable=False, server_default=sa.text("20")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["list_definition_id"], ["list_definition.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "public_slug", name="uq_submission_assignment_tenant_slug"),
        sa.CheckConstraint("source_type IN ('events', 'list')", name="ck_submission_assignment_source_type"),
        sa.CheckConstraint(
            "(source_type = 'events' AND tag_filter IS NOT NULL AND offset_days_before IS NOT NULL "
            "AND offset_days_after IS NOT NULL AND list_definition_id IS NULL AND deadline IS NULL) OR "
            "(source_type = 'list' AND list_definition_id IS NOT NULL AND deadline IS NOT NULL "
            "AND tag_filter IS NULL AND offset_days_before IS NULL AND offset_days_after IS NULL)",
            name="ck_submission_assignment_source_fields",
        ),
        sa.CheckConstraint("offset_days_before IS NULL OR offset_days_before >= 0", name="ck_submission_assignment_offset_before"),
        sa.CheckConstraint("offset_days_after IS NULL OR offset_days_after >= 0", name="ck_submission_assignment_offset_after"),
        sa.CheckConstraint("max_files_per_element >= 1", name="ck_submission_assignment_max_files"),
        sa.CheckConstraint("max_file_size_mb >= 1", name="ck_submission_assignment_max_size"),
    )
    op.create_index("idx_submission_assignment_tenant_active", "submission_assignment", ["tenant_id", "is_active"])

    # 3. submission_upload — Append-only Log, siehe Kommentar am SubmissionUpload-Modell.
    op.create_table(
        "submission_upload",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("assignment_id", sa.BigInteger(), nullable=False),
        sa.Column("event_id", sa.BigInteger(), nullable=True),
        sa.Column("list_entry_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["assignment_id"], ["submission_assignment.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["event.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["list_entry_id"], ["list_entry.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "(event_id IS NOT NULL AND list_entry_id IS NULL) OR (event_id IS NULL AND list_entry_id IS NOT NULL)",
            name="ck_submission_upload_exactly_one_target",
        ),
        sa.CheckConstraint("status IN ('submitted', 'reopened')", name="ck_submission_upload_status"),
    )
    op.create_index("idx_submission_upload_assignment_event", "submission_upload", ["assignment_id", "event_id"])
    op.create_index("idx_submission_upload_assignment_list_entry", "submission_upload", ["assignment_id", "list_entry_id"])

    # 4. submission_upload_file
    op.create_table(
        "submission_upload_file",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("upload_id", sa.BigInteger(), nullable=False),
        sa.Column("stored_file_id", sa.BigInteger(), nullable=False),
        sa.Column("sort_index", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["upload_id"], ["submission_upload.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["stored_file_id"], ["stored_file.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("upload_id", "sort_index", name="uq_submission_upload_file_sort"),
    )
    op.create_index("idx_submission_upload_file_upload", "submission_upload_file", ["upload_id"])

    # 5. Restricted DB-Rolle für den separaten abgabebox-backend-Service.
    #
    #    Isolationsziel (siehe Plan): dieser öffentliche, unauthentifizierte Service darf
    #    abgegebene Dateien (Pfad/Name/Checksum in stored_file) technisch NICHT auslesen
    #    können — nur INSERT. Einzige SELECT-Ausnahme: 5 nicht-sensitive Spalten auf
    #    submission_upload, um zu bestimmen, welche Elemente bereits abgegeben (verborgen)
    #    bzw. wieder offen sind. Baseline ist REVOKE ALL, danach explizites Allowlisting,
    #    damit künftige Migrationen der restricted Rolle nicht versehentlich Rechte vererben.
    password = os.environ.get("ABGABEBOX_DB_PASSWORD")
    if not password:
        raise RuntimeError(
            "ABGABEBOX_DB_PASSWORD muss vor dieser Migration gesetzt sein "
            "(Passwort fuer die restricted Postgres-Rolle 'hocx_abgabebox')."
        )
    db_name = os.environ.get("POSTGRES_DB", "hocx")
    # CREATE ROLE/ALTER ROLE sind DDL und unterstuetzen keine gebundenen Parameter an
    # dieser Grammatikposition. Das Passwort stammt aus einer server-seitigen Env-Var
    # (vom Betreiber gesetzt, kein Nutzereingabe-Pfad) - einfaches Escapen der
    # SQL-Anfuehrungszeichen genuegt, ist hier aber kein Injection-Risiko durch Dritte.
    escaped_password = password.replace("'", "''")

    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{ROLE_NAME}') THEN
                CREATE ROLE {ROLE_NAME} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
            END IF;
        END
        $$;
        """
    )
    op.execute(f"ALTER ROLE {ROLE_NAME} PASSWORD '{escaped_password}'")

    op.execute(f"GRANT CONNECT ON DATABASE {db_name} TO {ROLE_NAME}")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {ROLE_NAME}")
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {ROLE_NAME}")

    # Konfigurationstabellen: voller lesender Zugriff (keine Geheimnisse enthalten).
    for table in ("submission_assignment", "event", "list_definition", "list_entry"):
        op.execute(f"GRANT SELECT ON {table} TO {ROLE_NAME}")
    # Tenant: nur Minimalfelder (kein tag_config_json/profile_image_path).
    op.execute(f"GRANT SELECT (id, name, public_slug) ON tenant TO {ROLE_NAME}")
    # Participant: nur Namensfelder, damit Listen-Elemente vom Typ 'participant'/'participants'
    # auf der oeffentlichen Seite einen Namen anzeigen koennen - bewusst OHNE email/app_user_id.
    op.execute(f"GRANT SELECT (id, first_name, last_name, display_name) ON participant TO {ROLE_NAME}")
    # submission_upload: spaltenbeschraenktes SELECT, bewusst OHNE submitted_at und
    # ohne jeglichen Zugriff auf stored_file/submission_upload_file.
    op.execute(f"GRANT SELECT (id, assignment_id, event_id, list_entry_id, status) ON submission_upload TO {ROLE_NAME}")

    # Schreibender Zugriff: NUR INSERT, kein SELECT/UPDATE/DELETE.
    op.execute(f"GRANT INSERT ON submission_upload TO {ROLE_NAME}")
    op.execute(f"GRANT INSERT ON submission_upload_file TO {ROLE_NAME}")
    op.execute(f"GRANT INSERT ON stored_file TO {ROLE_NAME}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {ROLE_NAME}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {ROLE_NAME}")
    db_name = os.environ.get("POSTGRES_DB", "hocx")
    op.execute(f"REVOKE CONNECT ON DATABASE {db_name} FROM {ROLE_NAME}")
    op.execute(f"DROP ROLE IF EXISTS {ROLE_NAME}")

    op.drop_table("submission_upload_file")
    op.drop_table("submission_upload")
    op.drop_table("submission_assignment")
    op.drop_constraint("uq_tenant_public_slug", "tenant", type_="unique")
    op.drop_column("tenant", "public_slug")
