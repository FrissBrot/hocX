from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.core.admin_security import CurrentAdmin, get_optional_current_admin
from app.core.db import get_db
from app.schemas.admin import AdminLoginRequest, AdminSessionRead
from app.services.admin_auth_service import AdminAuthService

router = APIRouter()
service = AdminAuthService()


@router.post("/login", response_model=AdminSessionRead)
def login(payload: AdminLoginRequest, response: Response, db: Session = Depends(get_db)):
    return service.login(db, response, payload)


@router.post("/logout", response_model=dict[str, str])
def logout(response: Response):
    return service.logout(response)


@router.get("/session", response_model=AdminSessionRead)
def session(admin: CurrentAdmin | None = Depends(get_optional_current_admin)):
    return service.session(admin)
