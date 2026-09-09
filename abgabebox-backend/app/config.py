import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _load_file_secrets() -> None:
    """Resolve Docker-style VAR_FILE inputs without exposing values in Config.Env."""
    for variable in (
        "ABGABEBOX_DATABASE_URL",
        "FRIENDLY_CAPTCHA_API_KEY",
        "ABGABEBOX_CAPTCHA_SESSION_SECRET",
    ):
        file_variable = f"{variable}_FILE"
        if variable not in os.environ and (path := os.environ.get(file_variable)):
            os.environ[variable] = Path(path).read_text(encoding="utf-8").rstrip("\r\n")


_load_file_secrets()


class Settings(BaseSettings):
    """Eigenstaendige Settings fuer den oeffentlichen abgabebox-backend-Service.

    Verbindet sich mit derselben Postgres-Instanz wie das Haupt-hocX, aber ueber die
    restricted Rolle 'hocx_abgabebox' (siehe backend/alembic/versions/0020_abgabebox.py) -
    NICHT ueber die normale DATABASE_URL des Haupt-Backends.
    """

    app_name: str = "hocX Abgabebox API"
    database_url: str = Field(
        default="postgresql+psycopg://hocx_abgabebox:hocx_abgabebox@db:5432/hocx",
        validation_alias="ABGABEBOX_DATABASE_URL",
    )
    storage_root: str = Field(default="/app/storage", validation_alias="ABGABEBOX_STORAGE_ROOT")
    friendly_captcha_sitekey: str = Field(default="", validation_alias="FRIENDLY_CAPTCHA_SITEKEY")
    friendly_captcha_api_key: str = Field(default="", validation_alias="FRIENDLY_CAPTCHA_API_KEY")
    friendly_captcha_verify_url: str = Field(
        default="https://api.friendlycaptcha.com/api/v2/captcha/siteverify",
        validation_alias="FRIENDLY_CAPTCHA_VERIFY_URL",
    )
    # Signs the short-lived session token issued after a successful FriendlyCaptcha solve (see
    # captcha.py's mint_captcha_session_token) so a visitor only has to pass the actual bot-check
    # once per page visit instead of once per upload - a FriendlyCaptcha solution is single-use
    # against their siteverify endpoint (a second verify of the same solution fails), so this
    # token is what actually stays valid for repeat uploads, not the raw solution itself. Empty
    # default fails closed, same as friendly_captcha_api_key/sitekey above.
    captcha_session_secret: str = Field(default="", validation_alias="ABGABEBOX_CAPTCHA_SESSION_SECRET")
    captcha_session_ttl_minutes: int = Field(default=120, validation_alias="ABGABEBOX_CAPTCHA_SESSION_TTL_MINUTES")
    cors_allow_origin: str = Field(default="https://abgabe.example.com", validation_alias="ABGABEBOX_CORS_ORIGIN")
    clamav_host: str = Field(default="clamav", validation_alias="CLAMAV_HOST")
    clamav_port: int = Field(default=3310, validation_alias="CLAMAV_PORT")
    # Total disk space (quarantine + accepted files combined) a single tenant's abgabebox may
    # consume. The restricted DB role this service runs as has no SELECT on stored_file (see
    # 0020_abgabebox.py), so a DB-side SUM(file_size_bytes) isn't available here - the quota is
    # enforced by walking the tenant's storage directory instead.
    tenant_storage_quota_mb: int = Field(default=2048, validation_alias="ABGABEBOX_TENANT_STORAGE_QUOTA_MB")
    # A normal upload clears quarantine (scan + move-or-reject) within seconds - anything still
    # there after this long is debris from a crashed/interrupted request, never a real in-flight
    # upload. See storage.cleanup_stale_quarantine_files for why this is age-only, no DB check.
    quarantine_max_age_minutes: int = Field(default=60, validation_alias="ABGABEBOX_QUARANTINE_MAX_AGE_MINUTES")
    quarantine_cleanup_interval_minutes: int = Field(
        default=30, validation_alias="ABGABEBOX_QUARANTINE_CLEANUP_INTERVAL_MINUTES"
    )
    # Absolute, tenant-config-independent ceiling on how many files a single multipart upload
    # request may contain (audit finding, 2026-08-27). assignment.max_files_per_element is a
    # per-tenant/per-assignment setting that may legitimately be None ("unbegrenzt") - without a
    # separate hard cap, "unbegrenzt" also meant "no application-level limit on this request",
    # leaving only Starlette's own default (1000 files/request) standing between one request and
    # a sequential, per-file ClamAV scan (each up to a 30s socket timeout, see scanner.py) of up
    # to 1000 files. Enforced in routes/public.py's upload() before any file is read or scanned,
    # regardless of what max_files_per_element says.
    max_files_per_upload_request: int = Field(default=50, validation_alias="ABGABEBOX_MAX_FILES_PER_UPLOAD_REQUEST")
    # Distinguishes genuine local dev/test stacks (where running without a FriendlyCaptcha
    # account is a deliberate, accepted choice - see captcha.py's captcha_enabled()) from a real
    # deployment (audit finding, 2026-08-27: production must fail CLOSED - reject uploads -
    # when captcha can't be verified, never fail open). No such flag existed anywhere in this
    # service before this fix (checked main.py's existing startup checks and this file - neither
    # had one), so this is new. Deliberately fails safe: unset/unrecognized values are treated as
    # production-like, not dev-like - an operator must opt IN to the permissive behavior by
    # explicitly setting one of the values in _DEV_LIKE_ENVIRONMENTS below, rather than an
    # operator who simply forgot to set this ending up with silently-disabled captcha in prod.
    environment: str = Field(default="production", validation_alias="ABGABEBOX_ENVIRONMENT")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

# See Settings.environment's docstring above for the fail-safe-by-default rationale. Local dev
# (docker-compose.dev.yml) and the test stack (docker-compose.tests.yml) need to set
# ABGABEBOX_ENVIRONMENT to one of these to keep today's "no FriendlyCaptcha account needed
# locally" behavior - otherwise they now fail closed like production, since unset defaults to
# production-like.
_DEV_LIKE_ENVIRONMENTS = {"development", "dev", "test", "testing", "local"}


def is_dev_or_test_environment() -> bool:
    return settings.environment.strip().lower() in _DEV_LIKE_ENVIRONMENTS
