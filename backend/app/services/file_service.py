from pathlib import Path

from app.core.config import settings


class FileService:
    def ensure_storage(self) -> None:
        for path in [settings.storage_root, settings.export_root, settings.upload_root, settings.latex_template_root]:
            Path(path).mkdir(parents=True, exist_ok=True)

