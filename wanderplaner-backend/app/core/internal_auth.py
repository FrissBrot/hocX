"""Vertrauensgrenze zwischen hocX-Backend und Wanderplaner-Service.

Der Service hat keinen eigenen Login. Das hocX-Backend prueft Session, Mandant, Rolle und
Feature-Gating und ruft diesen Service dann mit einem gemeinsamen Geheimnis
(WANDERPLANER_INTERNAL_TOKEN) und dem bereits geprueften Kontext in Kopfzeilen auf. Ohne
gueltiges Token wird jede Anfrage abgelehnt - auch wenn der Service versehentlich von aussen
erreichbar waere, koennen Kopfzeilen nicht gefaelscht werden.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from urllib.parse import unquote

from fastapi import Header, HTTPException, status

from app.core.config import settings

TENANT_HEADER = "X-Hocx-Tenant-Id"
USER_HEADER = "X-Hocx-User-Id"
USER_NAME_HEADER = "X-Hocx-User-Name"


@dataclass(frozen=True)
class Caller:
    tenant_id: int
    user_id: int | None
    user_name: str | None


def verify_internal_token(authorization: str = Header(default="")) -> None:
    expected = settings.internal_token
    scheme, _, token = authorization.partition(" ")
    if not expected or scheme.lower() != "bearer" or not hmac.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Interner Zugriff verweigert")


def get_caller(
    authorization: str = Header(default=""),
    x_hocx_tenant_id: int | None = Header(default=None, alias=TENANT_HEADER),
    x_hocx_user_id: int | None = Header(default=None, alias=USER_HEADER),
    x_hocx_user_name: str | None = Header(default=None, alias=USER_NAME_HEADER),
) -> Caller:
    # Token zuerst: ohne gueltiges Token verraet die Antwort nichts ueber erwartete Kopfzeilen.
    verify_internal_token(authorization)
    if x_hocx_tenant_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{TENANT_HEADER} fehlt")
    # Kopfzeilen sind latin-1; hocX schickt den Namen deshalb URL-kodiert.
    return Caller(
        tenant_id=x_hocx_tenant_id,
        user_id=x_hocx_user_id,
        user_name=unquote(x_hocx_user_name) if x_hocx_user_name else None,
    )
