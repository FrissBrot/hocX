from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, issue_session_cookie
from app.schemas.mfa import (
    PasskeyRegistrationComplete,
    PasskeyRegistrationStartRead,
    TotpEnrollmentComplete,
    TotpEnrollmentStartRead,
    UserMfaRead,
)
from app.schemas.user import UserCreate, UserPasswordChange, UserRead, UserSelfUpdate, UserUpdate
from app.services.audit_service import AuditService
from app.services.mfa_service import MfaService
from app.services.user_service import UserService

router = APIRouter()
service = UserService()
mfa_service = MfaService()
audit = AuditService()


def _expected_origin(request: Request) -> str:
    origin = request.headers.get("origin")
    if origin:
        return origin
    host = request.headers.get("host") or request.url.netloc
    if host.startswith("localhost") or host.startswith("127.0.0.1"):
        return f"http://{host}"
    return f"https://{host}"


@router.get("", response_model=list[UserRead])
def list_users(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return service.list_users(db, user)


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    try:
        return service.create_user(db, payload, user)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="User could not be created") from exc


@router.get("/me", response_model=UserRead)
def get_me(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return service.get_self(db, user)


@router.patch("/me", response_model=UserRead)
def patch_me(
    payload: UserSelfUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    try:
        return service.update_self(db, user, payload)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Profile could not be updated") from exc


@router.get("/me/mfa", response_model=UserMfaRead)
def get_my_mfa(
    request: Request,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return mfa_service.get_self_overview(db, user, request.url.hostname)


@router.post("/me/mfa/totp/start", response_model=TotpEnrollmentStartRead)
def start_my_totp_enrollment(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return mfa_service.start_self_totp_enrollment(db, user)


@router.post("/me/mfa/totp/complete", response_model=UserMfaRead)
def complete_my_totp_enrollment(
    payload: TotpEnrollmentComplete,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    mfa_service.complete_self_totp_enrollment(
        db,
        user,
        flow_token=payload.flow_token,
        code=payload.code,
        label=payload.label,
    )
    issue_session_cookie(response, user.user_id, user.current_tenant_id, mfa_verified=True)
    return mfa_service.get_self_overview(db, user, request.url.hostname)


@router.post("/me/mfa/passkeys/start", response_model=PasskeyRegistrationStartRead)
def start_my_passkey_registration(
    request: Request,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return mfa_service.start_self_passkey_registration(
        db,
        user,
        request_host=request.url.hostname,
        request_origin=_expected_origin(request),
    )


@router.post("/me/mfa/passkeys/complete", response_model=UserMfaRead)
def complete_my_passkey_registration(
    payload: PasskeyRegistrationComplete,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    mfa_service.complete_self_passkey_registration(
        db,
        user,
        flow_token=payload.flow_token,
        label=payload.label,
        credential=payload.credential,
    )
    issue_session_cookie(response, user.user_id, user.current_tenant_id, mfa_verified=True)
    return mfa_service.get_self_overview(db, user, request.url.hostname)


@router.delete("/me/mfa/factors/{factor_id}", response_model=UserMfaRead)
def delete_my_mfa_factor(
    factor_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    result = mfa_service.delete_self_factor(db, user, factor_id)
    return result.model_copy(update={"can_add_passkey_here": mfa_service.can_add_passkey_here(request.url.hostname)})


@router.post("/me/password", response_model=UserRead)
def change_my_password(
    payload: UserPasswordChange,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    try:
        current = service.change_own_password(db, user, payload)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Password could not be changed") from exc
    audit.log(db, action="user.password_changed", actor=user, entity_type="user", entity_id=user.user_id)
    return current


@router.get("/{user_id}/mfa", response_model=UserMfaRead)
def get_user_mfa(
    user_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return mfa_service.get_managed_user_overview(db, user, user_id)


@router.delete("/{user_id}/mfa/factors/{factor_id}", response_model=UserMfaRead)
def delete_user_mfa_factor(
    user_id: int,
    factor_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    result = mfa_service.delete_managed_user_factor(db, user, user_id, factor_id)
    audit.log(
        db,
        action="user.mfa_factor_deleted",
        actor=user,
        entity_type="user_mfa_factor",
        entity_id=factor_id,
        details={"target_user_id": user_id},
    )
    return result


@router.get("/{user_id}", response_model=UserRead)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    current = service.get_user(db, user_id, user)
    if current is None:
        raise HTTPException(status_code=404, detail="User not found")
    return current


@router.patch("/{user_id}", response_model=UserRead)
def patch_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    try:
        current = service.update_user(db, user_id, payload, user)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="User could not be updated") from exc
    if current is None:
        raise HTTPException(status_code=404, detail="User not found")
    if payload.is_active is not None:
        action = "user.activated" if payload.is_active else "user.deactivated"
        audit.log(db, action=action, actor=user, entity_type="user", entity_id=user_id)
    return current


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    try:
        deleted = service.delete_user(db, user_id, user)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="User could not be deleted") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="User not found")
