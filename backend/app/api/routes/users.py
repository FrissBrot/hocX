from fastapi import APIRouter

router = APIRouter()


@router.get("", response_model=list[dict])
def list_users():
    return []

