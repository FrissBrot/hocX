from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, get_optional_current_user
from app.schemas.user import LoginRequest, SessionRead
from app.services.auth_service import AuthService

router = APIRouter()
service = AuthService()


@router.post("/login", response_model=SessionRead)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
    return service.login(db, response, payload)


@router.post("/logout", response_model=dict[str, str])
def logout(response: Response):
    return service.logout(response)


@router.get("/session", response_model=SessionRead)
def session(user: CurrentUser | None = Depends(get_optional_current_user)):
    return service.session(user)


@router.post("/select-tenant/{tenant_id}", response_model=SessionRead)
def select_tenant(
    tenant_id: int,
    response: Response,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return service.select_tenant(db, response, user, tenant_id)
