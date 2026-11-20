"""Frische Passkey-Bestätigung (Step-up) für kritische Admin-Aktionen (Security-Review M2/L7).

Eine Admin-Session allein genügt für diese Aktionen nicht: Der Browser holt zuerst eine Challenge
(``POST /api/admin/mfa/step-up/start`` mit Zweck, Methode, Pfad und SHA-256 des Request-Bodys), lässt
sie vom Passkey signieren und schickt die Assertion im Header ``X-Hocx-Step-Up`` (base64url-JSON
``{"flow_token": ..., "credential": {...}}``) mit der eigentlichen Anfrage. Das Backend prüft

- Zweck und Konto (der Vorgang gehört zu diesem Admin und Zweck),
- die Bindung: Methode, Pfad und Body-Hash der tatsächlichen Anfrage müssen dem entsprechen, was beim
  Start angegeben wurde (eine Bestätigung für «Admin X anlegen» gilt nicht für «Admin Y löschen»),
- die Assertion selbst (Origin, RP-ID, UV, Signatur, Zähler) - einmalig.

``require_step_up(purpose)`` prüft sofort (als Dependency). Routen, die vorher fachlich prüfen
wollen (Backup-Restore: ein Tippfehler soll keine Bestätigung verbrauchen), nehmen
``step_up_proof(purpose)`` und rufen ``proof.verify(db, admin_id)`` selbst auf.
"""
from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from functools import cache
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.admin_security import CurrentAdmin, get_current_admin
from app.core.db import get_db

STEP_UP_HEADER = "x-hocx-step-up"
MAX_HEADER_BYTES = 16 * 1024

# Zwecke - jede Bestätigung gilt nur für genau einen.
PURPOSES = frozenset({
    "passkey-manage",
    "admin-manage",
    "tenant-delete",
    "tenant-export",
    "storage-destructive",
    "backup-restore",
    "backup-settings",
    "catalog-change",
    "user-mfa-reset",
})


def step_up_binding(method: str, path: str, body: bytes) -> str:
    return f"{method.upper()} {path} {hashlib.sha256(body).hexdigest()}"


def _required() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": "step_up_required", "message": "Diese Aktion muss mit einem Passkey bestätigt werden"},
    )


@dataclass
class StepUpProof:
    purpose: str
    flow_token: str
    credential: dict[str, Any]
    binding: str

    def verify(self, db: Session, admin_id: int) -> None:
        from app.services.admin_mfa_service import AdminMfaService

        AdminMfaService().verify_step_up(
            db, admin_id=admin_id, purpose=self.purpose, flow_token=self.flow_token,
            credential=self.credential, binding=self.binding,
        )


async def _read_proof(request: Request, purpose: str) -> StepUpProof:
    raw = request.headers.get(STEP_UP_HEADER)
    if not raw or len(raw) > MAX_HEADER_BYTES:
        raise _required()
    try:
        data = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
        flow_token = data["flow_token"]
        credential = data["credential"]
    except (ValueError, KeyError, TypeError) as exc:
        raise _required() from exc
    if not isinstance(flow_token, str) or not isinstance(credential, dict):
        raise _required()
    body = await request.body()
    return StepUpProof(purpose, flow_token, credential, step_up_binding(request.method, request.url.path, body))


@cache  # je Zweck dieselbe Funktion: Tests können sie über dependency_overrides ersetzen
def step_up_proof(purpose: str):
    assert purpose in PURPOSES, purpose

    async def dependency(request: Request) -> StepUpProof:
        return await _read_proof(request, purpose)

    return dependency


@cache
def require_step_up(purpose: str):
    """Dependency: angemeldeter Admin mit frischer, an diese Anfrage gebundener Passkey-Bestätigung.
    Rollenprüfungen (Owner) bleiben Sache der Route."""
    assert purpose in PURPOSES, purpose

    async def dependency(
        request: Request,
        admin: CurrentAdmin = Depends(get_current_admin),
        db: Session = Depends(get_db),
    ) -> CurrentAdmin:
        proof = await _read_proof(request, purpose)
        await run_in_threadpool(proof.verify, db, admin.admin_id)
        return admin

    return dependency
