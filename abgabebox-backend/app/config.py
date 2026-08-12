from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
