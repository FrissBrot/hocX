"""Translate document-template part references at the service's API boundary."""
from copy import deepcopy
import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import DocumentTemplatePart
from app.services import public_id_service


def translate_part_ids(db: Session, config: dict | None, *, tenant_id: int, decode: bool) -> dict:
    result = deepcopy(config or {})
    references = []
    for container in (result.get("slots"), (result.get("theme") or {}).get("font_parts")):
        if isinstance(container, dict):
            references.extend((container, key) for key in container)
    assets = result.get("title_assets")
    if isinstance(assets, dict):
        references.extend((assets, key) for key in ("header_image_part_id", "footer_image_part_id") if key in assets)
    for container, key in references:
        value = container[key]
        if value is None:
            continue
        if decode:
            try:
                public_id = uuid.UUID(str(value))
            except (ValueError, TypeError) as exc:
                raise HTTPException(status_code=400, detail="Ungültiger Dokumentvorlagen-Bestandteil") from exc
            internal_id = public_id_service.resolve_internal_id(db, DocumentTemplatePart, public_id, tenant_id=tenant_id)
            if internal_id is None:
                raise HTTPException(status_code=400, detail="Dokumentvorlagen-Bestandteil nicht gefunden")
            container[key] = internal_id
        else:
            public_id = public_id_service.resolve_public_id(db, DocumentTemplatePart, value)
            container[key] = str(public_id) if public_id is not None else None
    return result
