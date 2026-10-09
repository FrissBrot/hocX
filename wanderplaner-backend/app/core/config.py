import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _load_file_secrets() -> None:
    """Docker-Secrets (VAR_FILE) aufloesen, ohne die Werte in Config.Env abzulegen."""
    for variable in ("WANDERPLANER_DATABASE_URL", "WANDERPLANER_APP_DATABASE_URL", "WANDERPLANER_INTERNAL_TOKEN"):
        file_variable = f"{variable}_FILE"
        if variable not in os.environ and (path := os.environ.get(file_variable)):
            os.environ[variable] = Path(path).read_text(encoding="utf-8").rstrip("\r\n")


_load_file_secrets()


class Settings(BaseSettings):
    """Eigenstaendige Settings des Wanderplaner-Service.

    Der Service ist nur im internen Docker-Netz erreichbar. Login, Mandant, Rollen und
    Feature-Gating prueft das hocX-Backend (app/api/routes/hiking_tours.py dort) und reicht
    den Aufruf mit WANDERPLANER_INTERNAL_TOKEN und den Kopfzeilen aus
    app/core/internal_auth.py weiter.
    """

    app_name: str = "hocX Wanderplaner API"
    # Admin-/Eigentuemerrolle: nur fuer Alembic und die Importskripte (scripts/import_*.py).
    database_url: str = Field(
        default="postgresql+psycopg://wanderplaner:wanderplaner@wanderplaner-db:5432/wanderplaner",
        validation_alias="WANDERPLANER_DATABASE_URL",
    )
    # Eingeschraenkte Laufzeitrolle wanderplaner_app (siehe alembic/versions/0001_initial.py).
    # Leer = Fallback auf database_url, nur fuer lokale Experimente gedacht.
    app_database_url: str = Field(default="", validation_alias="WANDERPLANER_APP_DATABASE_URL")
    # Leerer Default schlaegt geschlossen fehl: ohne Token wird jede Anfrage abgelehnt.
    internal_token: str = Field(default="", validation_alias="WANDERPLANER_INTERNAL_TOKEN")
    # Eigene Redis-DB-Nummer, damit Kartenkacheln/Hoehenprofil-Cache nie mit Sessions oder
    # Rate-Limits des hocX-Backends kollidieren.
    redis_url: str = Field(default="redis://redis:6379/2", validation_alias="WANDERPLANER_REDIS_URL")
    # Arbeitsverzeichnis fuer den pdflatex-Lauf des Kartendrucks. Das fertige PDF geht als
    # Antwort an hocX, das es als StoredFile ablegt - hier bleibt nichts liegen.
    work_root: str = Field(default="/tmp/wanderplaner-work", validation_alias="WANDERPLANER_WORK_ROOT")
    environment: str = Field(default="production", validation_alias="WANDERPLANER_ENVIRONMENT")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
