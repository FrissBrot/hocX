from fastapi import APIRouter

from app.services.export_service import ExportService

router = APIRouter()
service = ExportService()


@router.post("/protocols/{protocol_id}/exports/latex", response_model=dict[str, str | int])
def export_latex(protocol_id: int):
    return {"protocol_id": protocol_id, "format": "latex", "status": "scaffolded"}


@router.post("/protocols/{protocol_id}/exports/pdf", response_model=dict[str, str | int])
def export_pdf(protocol_id: int):
    return {"protocol_id": protocol_id, "format": "pdf", "status": "scaffolded"}


@router.get("/protocols/{protocol_id}/exports/latest", response_model=dict[str, str | int | None])
def latest_export(protocol_id: int):
    return service.latest_export_metadata(protocol_id)

