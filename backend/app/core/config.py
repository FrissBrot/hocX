import os
import sys
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_DEFAULTS = {
    "hocx-local-dev-secret",
    "hocx-local-dev-admin-secret",
    "change-me-to-a-random-32-plus-char-value",
    "change-me-to-a-different-random-32-plus-char-value",
    "changeme",
    "secret",
    "",
}


def _load_file_secrets() -> None:
    """Resolve Docker-style VAR_FILE inputs without exposing values in Config.Env."""
    for variable in ("DATABASE_URL", "APP_DATABASE_URL", "AUTH_SECRET", "ADMIN_AUTH_SECRET", "INITIAL_ADMIN_PASSWORD"):
        file_variable = f"{variable}_FILE"
        if variable not in os.environ and (path := os.environ.get(file_variable)):
            os.environ[variable] = Path(path).read_text(encoding="utf-8").rstrip("\r\n")


_load_file_secrets()


class Settings(BaseSettings):
    app_name: str = "hocX API"
    # docker-compose.yml/docker-compose.release.yml set HOCX_ENVIRONMENT (matching the
    # HOCX_* naming every other operator-facing variable uses, see scripts/lib/env.sh's
    # allowlist) - without this alias pydantic-settings looks for a bare ENVIRONMENT, which
    # nothing ever sets, so this silently stayed on the "production" default in every
    # environment including local dev. Harmless before the demo-data production guard below
    # existed; now it makes that guard fire in dev too, since INITIAL_ADMIN_EMAIL there is
    # an @hocx.local address. Mirrors abgabebox-backend/app/config.py's Settings.environment.
    environment: str = Field(default="production", validation_alias="HOCX_ENVIRONMENT")
    # Admin/migration connection (superuser role) - used by alembic (see alembic/env.py).
    database_url: str = "postgresql+psycopg://hocx:hocx@db:5432/hocx"
    # Runtime connection for the FastAPI app itself, using the least-privilege
    # 'hocx_app' role (see alembic/versions/0070_restrict_app_db_role.py) instead of the
    # superuser role above - audit finding, 2026-08-26: previously the app served every
    # request as Postgres superuser, so a SQL-injection bug or a compromised backend
    # process would have had full control over the whole Postgres server (all databases,
    # CREATE ROLE, RLS bypass, ...), not just this app's tables. Falls back to
    # database_url when unset so existing local/CI setups that only define DATABASE_URL
    # keep working unchanged.
    app_database_url: str = ""
    storage_root: str = "/app/storage"
    latex_template_root: str = "/app/storage/latex_templates"
    export_root: str = "/app/storage/exports"
    upload_root: str = "/app/storage/uploads"
    abgabebox_storage_root: str = "/app/abgabebox-storage"
    abgabebox_base_url: str = "https://upload.example.com"
    traefik_domain: str | None = None
    traefik_abgabebox_domain: str | None = None
    traefik_dynamic_config_dir: str = "/app/traefik_dynamic"
    domain_health_check_interval_minutes: int = 30
    abgabebox_rescan_interval_minutes: int = 15
    word_import_rescan_interval_minutes: int = 15
    export_cleanup_interval_minutes: int = 1440
    export_retention_days: int = 30
    # Retention sweep for audit_log/system_error_log (audit finding, 2026-08-26: neither
    # table had any cleanup, both grow unbounded forever). audit_log default is
    # deliberately long (~2 years) since it's the compliance/security trail - review
    # against your own legal retention duty before relying on this default.
    log_cleanup_interval_minutes: int = 1440
    audit_log_retention_days: int = 730
    error_log_retention_days: int = 90
    # Mirrors the abgabebox subapp's ABGABEBOX_TENANT_STORAGE_QUOTA_MB - protocol-image
    # uploads had only a per-file limit (MAX_UPLOAD_BYTES), no per-tenant total at all
    # (audit finding, 2026-08-25), a real risk given this app's two prior disk-full
    # outages. Same 2 GB default.
    protocol_image_storage_quota_mb: int = 2048
    auth_secret: str = "hocx-local-dev-secret"
    auth_session_cookie: str = "hocx_session"
    auth_session_ttl_hours: int = 72
    auth_secure_cookies: bool = True
    admin_auth_secret: str = "hocx-local-dev-admin-secret"
    admin_session_cookie: str = "hocx_admin_session"
    admin_session_ttl_hours: int = 12
    initial_admin_email: str | None = None
    initial_admin_password: str | None = None
    clamav_host: str = "clamav"
    clamav_port: int = 3310
    redis_url: str = "redis://redis:6379/0"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    def validate_for_production(self) -> None:
        if self.auth_secret in _INSECURE_DEFAULTS or len(self.auth_secret) < 32:
            print(
                "FATAL: AUTH_SECRET is insecure or not set. "
                "Set a random value of at least 32 characters in .env.",
                file=sys.stderr,
            )
            sys.exit(1)
        if self.admin_auth_secret in _INSECURE_DEFAULTS or len(self.admin_auth_secret) < 32:
            print(
                "FATAL: ADMIN_AUTH_SECRET is insecure or not set. "
                "Set a random value of at least 32 characters in .env.",
                file=sys.stderr,
            )
            sys.exit(1)
        if self.environment.strip().lower() == "production":
            if not self.auth_secure_cookies:
                print("FATAL: AUTH_SECURE_COOKIES must be true in production.", file=sys.stderr)
                sys.exit(1)
            if self.initial_admin_email and self.initial_admin_email.lower().endswith("@hocx.local"):
                print("FATAL: A local development admin identity is forbidden in production.", file=sys.stderr)
                sys.exit(1)
            if self.initial_admin_password == "ChangeMe123!":
                print("FATAL: The known development admin password is forbidden in production.", file=sys.stderr)
                sys.exit(1)

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() == "production"


settings = Settings()
settings.validate_for_production()
