"""Öffentliche Echtheitsprüfung von PDFs aus hocX (Prüfseite /verify der Abgabebox).

Der Browser berechnet den SHA-256 der Datei selbst (Web Crypto API) und schickt nur den Hash und
optional die Dokument-ID aus dem QR-Code. Hier wird nichts gespeichert: kein Cookie, keine
Session, weder Hash noch IP (das Rate-Limit hält Traefik im Speicher). Eigener Traefik-Router mit
kleinem Body-Limit und eigenem Rate-Limit (docker-compose.yml, traefik_config_service).

Prüf-Domains der Mandanten (z. B. verify.verein.ch, Feature verify_domain) zeigen dieselbe Seite.
GET /public/verify/site liefert deren Kopf (Name, Logo, Bestätigung); die Seite ruft das
serverseitig über das interne Netz mit dem Host der Anfrage auf.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import repository
from app.config import settings
from app.db import get_db
from app.schemas import VerifyRequest, VerifyResult, VerifySiteRead

router = APIRouter()


@router.post("/public/verify", response_model=VerifyResult, response_model_exclude_none=True)
def verify(body: VerifyRequest, response: Response, db: Session = Depends(get_db)) -> VerifyResult:
    response.headers["Cache-Control"] = "no-store"
    try:
        row = repository.verify_document(db, sha256=body.sha256)
    except SQLAlchemyError as exc:
        db.rollback()
        # Landet über den HTTPException-Handler (main.py) mit Ursache im system_error_log.
        raise HTTPException(status_code=503, detail="Die Prüfung ist gerade nicht verfügbar.") from exc
    if row is None:
        if body.document_id is not None and body.page_fingerprints is not None:
            return _verify_by_id(db, body)
        return VerifyResult(found=False)
    return VerifyResult(
        found=True,
        document_id_matches=(row["document_id"] == body.document_id) if body.document_id is not None else None,
        **row,
    )


def _verify_by_id(db: Session, body: VerifyRequest) -> VerifyResult:
    """Zweiter Schritt der Prüfseite: Hash unbekannt, aber die Datei trägt eine Dokument-ID. Dann
    heisst es nie «Original», sondern «gehört zu Dokument X, wurde verändert», mit Seitenvergleich,
    falls das Register Fingerabdrücke hat. Unbekannte IDs ergeben dasselbe wie ein unbekannter Hash
    (UUIDv7, nicht erratbar; Rate-Limit wie die Hash-Prüfung)."""
    try:
        row = repository.verify_document_pages(db, document_id=str(body.document_id), fingerprints=list(body.page_fingerprints or []))
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Die Prüfung ist gerade nicht verfügbar.") from exc
    if row is None:
        return VerifyResult(found=False)
    matches = row.pop("page_matches")
    page_count = row.pop("page_count")
    return VerifyResult(
        found=False,
        modified=True,
        page_count=page_count if matches is not None else None,
        changed_pages=[index + 1 for index, same in enumerate(matches) if not same] if matches is not None else None,
        **row,
    )


@router.get("/public/verify/site", response_model=VerifySiteRead, response_model_exclude_none=True)
def verify_site(
    response: Response,
    domain: str = Query(min_length=1, max_length=253, pattern=r"^[A-Za-z0-9.-]+(:[0-9]{1,5})?$"),
    db: Session = Depends(get_db),
) -> VerifySiteRead:
    response.headers["Cache-Control"] = "no-store"
    host = domain.split(":", 1)[0].lower().rstrip(".")
    try:
        row = repository.verify_site(db, domain=host)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Die Prüfung ist gerade nicht verfügbar.") from exc
    return VerifySiteRead(central_verify_url=settings.central_verify_url, **(row or {}))
