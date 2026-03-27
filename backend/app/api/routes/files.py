from fastapi import APIRouter, UploadFile

router = APIRouter()


@router.post("/protocol-elements/{protocol_element_id}/images", response_model=dict[str, str])
async def upload_image(protocol_element_id: int, file: UploadFile):
    return {"message": f"Upload scaffolded for protocol element {protocol_element_id}", "filename": file.filename}


@router.delete("/protocol-images/{image_id}", response_model=dict[str, str])
def delete_image(image_id: int):
    return {"message": f"DELETE /protocol-images/{image_id} scaffolded"}

