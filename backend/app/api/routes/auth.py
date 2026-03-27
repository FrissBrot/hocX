from fastapi import APIRouter

from app.services.auth_service import AuthService

router = APIRouter()
service = AuthService()


@router.get("/login", response_model=dict[str, str])
def login_stub():
    return service.login_stub()

