import uuid

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.core.db import get_db
from app.core.config import settings
from app.core.security import CurrentUser, get_current_user, require_reader, require_writer
from app.models import ProtocolElementBlock, ProtocolImage, StoredFile
from app.schemas.protocol import ProtocolImageRead
from app.services import public_id_service
from app.services.access_service import AccessService
from app.services.file_service import FileService, _safe_storage_path

router = APIRouter()
service = FileService()
access_service = AccessService()

@router.get("/protocol-element-blocks/{protocol_element_block_id}/images", response_model=list[ProtocolImageRead])
def list_images(
    protocol_element_block_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    block = public_id_service.get_by_public_id(db, ProtocolElementBlock, protocol_element_block_id)
    if block is None:
        raise HTTPException(status_code=404, detail="Protocol element block not found")
    access_service.ensure_can_read_protocol_block(db, user, block.id)
    return service.list_protocol_images(db, block.id)


@router.post("/protocol-element-blocks/{protocol_element_block_id}/images", response_model=ProtocolImageRead)
async def upload_image(
    protocol_element_block_id: uuid.UUID,
    file: UploadFile,
    title: str | None = Form(default=None),
    caption: str | None = Form(default=None),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    protocol_element_block = public_id_service.get_by_public_id(db, ProtocolElementBlock, protocol_element_block_id)
    if protocol_element_block is None:
        raise HTTPException(status_code=404, detail="Protocol element block not found")
    access_service.ensure_can_read_protocol_block(db, user, protocol_element_block.id)
    try:
        return await service.save_protocol_image(
            db,
            protocol_element_block=protocol_element_block,
            file=file,
            title=title,
            caption=caption,
            created_by=None,
        )
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Image could not be uploaded") from exc


@router.delete("/protocol-images/{image_id}", response_model=dict[str, str])
def delete_image(
    image_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    protocol_image = public_id_service.get_by_public_id(db, ProtocolImage, image_id)
    if protocol_image is None:
        raise HTTPException(status_code=404, detail="Image not found")
    access_service.ensure_can_read_protocol_block(db, user, protocol_image.protocol_element_block_id)
    try:
        deleted = service.delete_protocol_image(db, protocol_image.id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Image could not be deleted") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Image not found")
    return {"message": "Image deleted"}


@router.get("/stored-files/{stored_file_id}/content")
def get_stored_file_content(
    stored_file_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    stored_file = public_id_service.get_by_public_id(db, StoredFile, stored_file_id)
    if stored_file is None:
        raise HTTPException(status_code=404, detail="Stored file not found")
    access_service.ensure_can_read_stored_file(db, user, stored_file.id)
    if stored_file.scan_status == "infected":
        raise HTTPException(status_code=403, detail="Datei wurde von der Virenprüfung als infiziert erkannt und ist gesperrt")
    if stored_file.scan_status == "pending":
        raise HTTPException(status_code=425, detail="Datei wird noch auf Schadsoftware geprüft, bitte in Kürze erneut versuchen")
    file_path = _safe_storage_path(settings.storage_root, stored_file.storage_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File missing on filesystem")
    # SECURITY: set nosniff so a browser never MIME-sniffs the content and renders it
    # inline against our wishes, mirroring submission_assignments.get_submission_file_content.
    # inline also covers images now, not just PDF (audit finding, 2026-08-25) - protocol
    # images are rendered directly via <img src> pointing at this same endpoint (see
    # focused-element-editor.tsx's LightboxImage/content_url), which "attachment" would
    # otherwise force browsers to treat as a download instead of image data to paint.
    # nosniff already closes the MIME-confusion risk "attachment" was guarding against
    # for a real image mime type.
    is_inline_safe = stored_file.mime_type == "application/pdf" or (stored_file.mime_type or "").startswith("image/")
    return FileResponse(
        path=file_path,
        media_type=stored_file.mime_type,
        filename=stored_file.original_name,
        content_disposition_type="inline" if is_inline_safe else "attachment",
        headers={"X-Content-Type-Options": "nosniff"},
    )
