from fastapi import APIRouter, Depends

from app.core.security import CurrentUser, get_current_user
from app.services.auth_service import AuthService

router = APIRouter()
service = AuthService()


@router.get("/login", response_model=dict[str, str])
def login_stub():
    return service.login_stub()


@router.get("/session", response_model=dict[str, int | str | None])
def session_stub(user: CurrentUser = Depends(get_current_user)):
    return service.session_stub(user)
