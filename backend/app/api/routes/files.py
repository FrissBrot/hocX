from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.core.db import get_db
from app.core.config import settings
from app.core.security import CurrentUser, get_current_user, require_reader, require_writer
from app.models import ProtocolElementBlock
from app.schemas.protocol import ProtocolImageRead
from app.services.file_service import FileService

router = APIRouter()
service = FileService()

@router.get("/protocol-element-blocks/{protocol_element_block_id}/images", response_model=list[ProtocolImageRead])
def list_images(
    protocol_element_block_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    return service.list_protocol_images(db, protocol_element_block_id)


@router.post("/protocol-element-blocks/{protocol_element_block_id}/images", response_model=ProtocolImageRead)
async def upload_image(
    protocol_element_block_id: int,
    file: UploadFile,
    title: str | None = Form(default=None),
    caption: str | None = Form(default=None),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    protocol_element_block = db.get(ProtocolElementBlock, protocol_element_block_id)
    if protocol_element_block is None:
        raise HTTPException(status_code=404, detail="Protocol element block not found")
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
    image_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    try:
        deleted = service.delete_protocol_image(db, image_id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Image could not be deleted") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Image not found")
    return {"message": "Image deleted"}


@router.get("/stored-files/{stored_file_id}/content")
def get_stored_file_content(
    stored_file_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    stored_file = service.get_stored_file(db, stored_file_id)
    if stored_file is None:
        raise HTTPException(status_code=404, detail="Stored file not found")
    file_path = Path(settings.storage_root) / stored_file.storage_path
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File missing on filesystem")
    return FileResponse(path=file_path, media_type=stored_file.mime_type, filename=stored_file.original_name)
