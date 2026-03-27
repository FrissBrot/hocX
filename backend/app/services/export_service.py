from pathlib import Path

from app.core.config import settings


class ExportService:
    def latest_export_metadata(self, protocol_id: int) -> dict[str, str | int | None]:
        pdf_path = Path(settings.export_root) / f"protocol-{protocol_id}.pdf"
        return {
            "protocol_id": protocol_id,
            "latest_format": "pdf" if pdf_path.exists() else None,
            "path": str(pdf_path) if pdf_path.exists() else None,
        }

