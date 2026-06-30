import sys

from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_DEFAULTS = {"hocx-local-dev-secret", "changeme", "secret", ""}


class Settings(BaseSettings):
    app_name: str = "hocX API"
    database_url: str = "postgresql+psycopg://hocx:hocx@db:5432/hocx"
    storage_root: str = "/app/storage"
    latex_template_root: str = "/app/storage/latex_templates"
    export_root: str = "/app/storage/exports"
    upload_root: str = "/app/storage/uploads"
    auth_secret: str = "hocx-local-dev-secret"
    auth_session_cookie: str = "hocx_session"
    auth_session_ttl_hours: int = 72
    auth_secure_cookies: bool = True

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    def validate_for_production(self) -> None:
        if self.auth_secret in _INSECURE_DEFAULTS or len(self.auth_secret) < 32:
            print(
                "FATAL: AUTH_SECRET is insecure or not set. "
                "Set a random value of at least 32 characters in .env.",
                file=sys.stderr,
            )
            sys.exit(1)


settings = Settings()
settings.validate_for_production()
