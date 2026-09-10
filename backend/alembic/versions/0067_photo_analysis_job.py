"""Photo-culling Phase 3 (aesthetic/face-quality scoring): photo_analysis_job table,
face_quality_score column on stored_file, and a dedicated restricted DB role for the
separate photo-analysis-worker container."""

revision = "0067_photo_analysis_job"
down_revision = "0066_stored_file_photo_quality"
branch_labels = None
depends_on = None

import os

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

PHOTO_WORKER_ROLE = "hocx_photo_worker"


def _read_password(env_var: str, role_name: str) -> str:
    # Same helper as 0001_initial_schema.py's role bootstrap - duplicated rather than
    # imported since alembic revision modules are meant to stand alone (each one is a
    # frozen snapshot; importing another revision's internals would couple this migration
    # to that file's future edits).
    password = os.environ.get(env_var)
    if not password and (password_file := os.environ.get(f"{env_var}_FILE")):
        with open(password_file, encoding="utf-8") as secret_file:
            password = secret_file.read().rstrip("\r\n")
    if not password:
        raise RuntimeError(
            f"{env_var} muss vor dieser Migration gesetzt sein "
            f"(Passwort fuer die restricted Postgres-Rolle '{role_name}')."
        )
    return password


def _create_role(role_name: str, password: str) -> None:
    escaped_password = password.replace("'", "''")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{role_name}') THEN
                CREATE ROLE {role_name} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
                    NOREPLICATION NOBYPASSRLS NOINHERIT;
            END IF;
        END
        $$;
        """
    )
    op.execute(f"ALTER ROLE {role_name} PASSWORD '{escaped_password}'")


def upgrade():
    op.add_column("stored_file", sa.Column("face_quality_score", sa.Float, nullable=True))

    op.create_table(
        "photo_analysis_job",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuidv7()")),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'queued'")),
        # StoredFile.id (internal bigint) values this job should analyze - the worker only
        # ever looks rows up directly, it never needs to speak the public API's id scheme.
        sa.Column("stored_file_ids", postgresql.JSONB(), nullable=False),
        sa.Column("requested_by", sa.BigInteger(), sa.ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_photo_analysis_job_tenant", "photo_analysis_job", ["tenant_id"])
    # Lets the worker's "next queued job" query (status = 'queued' ORDER BY created_at
    # FOR UPDATE SKIP LOCKED) pick the oldest queued job efficiently instead of a full scan.
    op.create_index("idx_photo_analysis_job_status_created", "photo_analysis_job", ["status", "created_at"])

    bind = op.get_bind()
    db_name = bind.execute(sa.text("SELECT current_database()")).scalar()

    # Dedicated, minimally-privileged role for photo-analysis-worker: its own container,
    # running third-party CV/ML inference (OpenCV/onnxruntime) over untrusted user-uploaded
    # image bytes - a meaningfully different risk profile than the rest of the backend, so
    # it gets the same "own restricted role" treatment as hocx_abgabebox rather than reusing
    # hocx_app's broad access to the entire multi-tenant schema (finances, participant PII,
    # etc.). If it were ever compromised via a malicious-image parsing bug, this role can
    # only read a handful of stored_file columns and write one score column back.
    _create_role(PHOTO_WORKER_ROLE, _read_password("PHOTO_WORKER_DB_PASSWORD", PHOTO_WORKER_ROLE))
    op.execute(f"GRANT CONNECT ON DATABASE {db_name} TO {PHOTO_WORKER_ROLE}")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {PHOTO_WORKER_ROLE}")

    # Just enough to locate+read the file off disk (id/tenant_id/storage_path/mime_type) and
    # write back one score - not scan_status, checksum, tags, original_name, or anything else.
    op.execute(f"GRANT SELECT(id, tenant_id, storage_path, mime_type) ON TABLE public.stored_file TO {PHOTO_WORKER_ROLE}")
    op.execute(f"GRANT UPDATE(face_quality_score) ON TABLE public.stored_file TO {PHOTO_WORKER_ROLE}")
    # SELECT+UPDATE only - the backend (hocx_app) owns creating/deleting jobs, the worker
    # only ever transitions an existing job's status/timestamps/error.
    op.execute(f"GRANT SELECT, UPDATE ON TABLE public.photo_analysis_job TO {PHOTO_WORKER_ROLE}")


def downgrade():
    bind = op.get_bind()
    db_name = bind.execute(sa.text("SELECT current_database()")).scalar()

    op.execute(f"REVOKE ALL ON TABLE public.photo_analysis_job FROM {PHOTO_WORKER_ROLE}")
    op.execute(f"REVOKE ALL ON TABLE public.stored_file FROM {PHOTO_WORKER_ROLE}")
    # A role can't be dropped while it still holds any privilege, including the schema/
    # database-level GRANTs from upgrade() above (found while downgrading a real dev
    # database: DROP ROLE failed with "cannot be dropped because some objects depend on
    # it" / "privileges for schema public" / "privileges for database ...").
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {PHOTO_WORKER_ROLE}")
    op.execute(f"REVOKE CONNECT ON DATABASE {db_name} FROM {PHOTO_WORKER_ROLE}")
    op.execute(f"DROP ROLE IF EXISTS {PHOTO_WORKER_ROLE}")
    op.drop_index("idx_photo_analysis_job_status_created", table_name="photo_analysis_job")
    op.drop_index("idx_photo_analysis_job_tenant", table_name="photo_analysis_job")
    op.drop_table("photo_analysis_job")
    op.drop_column("stored_file", "face_quality_score")
