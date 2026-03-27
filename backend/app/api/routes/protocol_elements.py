from fastapi import APIRouter

from app.services.autosave_service import AutosaveService

router = APIRouter()
autosave_service = AutosaveService()


@router.get("/protocols/{protocol_id}/elements", response_model=list[dict])
def list_protocol_elements(protocol_id: int):
    return [{"protocol_id": protocol_id, "message": "Protocol elements endpoint scaffolded"}]


@router.patch("/protocol-elements/{protocol_element_id}", response_model=dict[str, str])
def patch_protocol_element(protocol_element_id: int):
    return {"message": f"PATCH /protocol-elements/{protocol_element_id} scaffolded"}


@router.put("/protocol-elements/{protocol_element_id}/text", response_model=dict)
def put_protocol_text(protocol_element_id: int, payload: dict):
    return autosave_service.save_text_block(protocol_element_id, payload.get("content", ""))

