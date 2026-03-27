from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "hocX API"
    database_url: str = "postgresql+psycopg://hocx:hocx@db:5432/hocx"
    storage_root: str = "/app/storage"
    latex_template_root: str = "/app/storage/latex_templates"
    export_root: str = "/app/storage/exports"
    upload_root: str = "/app/storage/uploads"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

