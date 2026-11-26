"""Google-Auswahl im Datei-Import: Drive-Picker und Google-Fotos-Sitzung (Plan §3, §5.3, P2/P3).

Beide Anbieter haben keinen Ordnerbaum (drive.file bzw. Photos Picker API):

- Google Drive läuft auf einer **eigenen Origin** ohne hocX-Sitzung (Security-Review 1.7, N3,
  ``services/cloud_import/picker_tickets.py``): ``POST /cloud-import/jobs/{id}/google-drive/picker-ticket``
  (mit Sitzung, eigener Auftrag, Entwurf) gibt die Adresse der Picker-Seite mit einem einmaligen
  Ticket im Fragment. Die Seite tauscht es ohne Sitzung gegen das kurzlebige ``drive.file``-Token
  (``POST /cloud-import/picker/google-drive/token``) und schickt die Auswahl mit einem zweiten
  Ticket (``…/apply``). ``Cache-Control: no-store`` auf allem, was ein Token enthält.
- ``POST /cloud-import/jobs/{id}/google-photos/session`` legt eine Picker-Sitzung bei Google an und
  gibt nur die ``pickerUri`` (immer ``https://photos.google.com/…``) zurück; die Sitzungs-ID bleibt
  am Auftrag (``listing_state.picker_session``). ``…/session/poll`` fragt den Stand ab und startet
  bei ``mediaItemsSet`` das Auflisten (Auswahl ``session:<id>``).

Alle Routen: ``files.import`` (über ``cloud_import._load``, bei den Ticket-Routen für die Person des
Tickets neu geprüft), eigener Auftrag, Rate-Limit.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from html import escape

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.routes import cloud_import as routes
from app.auth_security import sessions as auth_sessions
from app.core.client_ip import rate_limit_source
from app.core.db import get_db
from app.core.tenant_scope import bind_tenant_scope
from app.core.rate_limit import enforce_rate_limit
from app.core.permissions import P
from app.core.config import settings
from app.core.security import CurrentUser, build_current_user, get_current_user, require_permission
from app.models.entities import AppUser
from app.services.audit_service import AuditService
from app.services.cloud_import import connections, picker_tickets, providers
from app.services.cloud_import.http import ProviderError
from app.services.cloud_import.jobs import ImportFailure
from app.services.cloud_import.providers.base import ReauthRequired
from app.services.cloud_import.providers.google_common import GOOGLE_ID
from app.services.cloud_import.providers.google_drive import PICKER_MAX_ITEMS

router = APIRouter()

_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _google_job(db: Session, user: CurrentUser, job_id: uuid.UUID, source: str, *, lock: bool = False):
    job = routes._load(db, user, job_id, owner=True, lock=lock)
    if job.source != source:
        raise routes._http(ImportFailure(409, "wrong_source"))
    if job.status != "draft":
        raise routes._http(ImportFailure(409, "invalid_status", {"status": job.status}))
    provider, ctx, connection = routes._remote_context(db, job)
    if not provider.has_scope(ctx):
        # Granulare Zustimmung: der Zugriff auf Dateien/Fotos wurde abgewählt → neu anmelden
        raise routes._http(ImportFailure(409, "missing_scope"))
    return job, provider, ctx, connection


# --- Google Drive: Picker auf eigener Origin (Tickets) ------------------------------------------


class DrivePickerRead(BaseModel):
    access_token: str
    api_key: str
    app_id: str
    expires_in: int
    max_items: int
    fake: bool = False


class PickerTicketRead(BaseModel):
    # https://<CLOUD_IMPORT_PICKER_DOMAIN>/google-picker#ticket=… (Ticket nur im Fragment)
    picker_url: str


def _wizard_return_url(db: Session, tenant_id: int, request_host: str | None, job_id: uuid.UUID) -> str:
    """Rücksprung in den Wizard (absolut, die Picker-Seite liegt auf einer anderen Origin): die
    zentrale Domain oder die aktive App-Domain des Vereins (wie der OAuth-Rücksprung), sonst die
    Basis der Callbacks - nie eine Adresse aus dem Browser (kein Open Redirect)."""
    host = routes._allowed_return_host(db, tenant_id, request_host)
    if host:
        base = f"https://{host}"
    elif settings.cloud_import_redirect_base_url:
        base = settings.cloud_import_redirect_base_url.rstrip("/")
    elif settings.traefik_domain:
        base = f"https://{settings.traefik_domain}"
    else:
        raise routes._http(ImportFailure(404, "provider_unavailable"))
    return f"{base}/files/import?job={job_id}"


@router.post("/cloud-import/jobs/{job_id}/google-drive/picker-ticket", response_model=PickerTicketRead)
def google_drive_picker_ticket(
    job_id: uuid.UUID, request: Request, response: Response, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user),
):
    """Ticket für die Picker-Seite auf ihrer eigenen Origin (einmalig, 10 min, an Auftrag und Person gebunden)."""
    require_permission(user, P.FILES_IMPORT)
    enforce_rate_limit(f"cloud-import-picker:{user.user_id}", limit=60, period_seconds=600)
    if picker_tickets.picker_origin() is None or not providers.is_available("google_drive"):
        raise routes._http(ImportFailure(404, "provider_unavailable"))
    job, provider, _ctx, _connection = _google_job(db, user, job_id, "google_drive")
    ticket = picker_tickets.issue(picker_tickets.TicketData(
        stage="token", tenant_id=job.tenant_id, user_id=user.user_id, job_id=str(job.id),
        return_url=_wizard_return_url(db, job.tenant_id, request.headers.get("host"), job.id),
        issued_at=datetime.now(UTC).timestamp(), session_id=str(user.session_id) if user.session_id else None,
    ))
    AuditService().log(
        db, action="cloud_import.picker_ticket", actor=user, entity_type="import_job",
        details={"job_id": str(job.id), "provider": provider.key}, commit=False,
    )
    db.commit()
    response.headers.update(_NO_STORE)
    return PickerTicketRead(picker_url=picker_tickets.picker_url(ticket))


class PickerTicketIn(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    ticket: str = Field(min_length=20, max_length=100)


class PickerTokenRead(DrivePickerRead):
    # Zweites, eigenes Ticket für das Übernehmen der Auswahl
    apply_ticket: str
    return_url: str


class PickerApplyIn(PickerTicketIn):
    file_ids: list[str] = Field(min_length=1, max_length=PICKER_MAX_ITEMS)


class PickerApplyRead(BaseModel):
    return_url: str


def _ticket_failure(exc: HTTPException, data: picker_tickets.TicketData) -> HTTPException:
    """Fehler nach einem gültigen Ticket: die Rücksprung-Adresse mitgeben (die Seite kennt sie sonst nicht)."""
    if isinstance(exc.detail, dict):
        return HTTPException(status_code=exc.status_code, detail={**exc.detail, "return_url": data.return_url})
    return exc


def _ticket_user(db: Session, data: picker_tickets.TicketData) -> CurrentUser:
    """Person des Tickets im Mandanten des Tickets: Konto aktiv, Anmeldung erlaubt, keine danach
    beendeten Sitzungen; die Berechtigung prüfen die Routen danach wie mit Sitzung."""
    bind_tenant_scope(db, data.tenant_id)
    account = db.get(AppUser, data.user_id)
    revoked = account.session_revoke_at if account is not None else None
    if (
        account is None
        or account.tenant_id != data.tenant_id
        or not account.is_active
        or not account.login_enabled
        or account.has_left
        or (revoked is not None and revoked.timestamp() >= data.issued_at)
        # Ausstellende Sitzung abgemeldet, widerrufen oder abgelaufen (Session-Register)
        or (data.session_id is not None and auth_sessions.validate(db, data.session_id, data.user_id, touch=False) is None)
    ):
        raise HTTPException(status_code=404, detail={"code": "ticket_invalid", "message": "ticket_invalid", "params": {}})
    user = build_current_user(db, account, mfa_verified=True)
    require_permission(user, P.FILES_IMPORT)
    return user


def _consume(payload: PickerTicketIn, request: Request, stage: str) -> picker_tickets.TicketData:
    # Ohne Sitzung: Grenze je Quell-IP (Tickets sind ohnehin zufällig, einmalig und kurzlebig)
    enforce_rate_limit(f"cloud-import-picker-ticket:{rate_limit_source(request)}", limit=60, period_seconds=600)
    data = picker_tickets.consume(payload.ticket, stage)
    if data is None:
        raise HTTPException(status_code=404, detail={"code": "ticket_invalid", "message": "ticket_invalid", "params": {}})
    return data


@router.post("/cloud-import/picker/google-drive/token", response_model=PickerTokenRead)
def google_drive_picker_token(payload: PickerTicketIn, request: Request, response: Response, db: Session = Depends(get_db)):
    """Für die Picker-Seite (eigene Origin, ohne Sitzung): Token-Ticket → kurzlebiges Access-Token der
    Verbindung (nur drive.file), API-Key, App-ID und ein Apply-Ticket."""
    response.headers.update(_NO_STORE)
    data = _consume(payload, request, "token")
    try:
        user = _ticket_user(db, data)
        job, provider, ctx, connection = _google_job(db, user, uuid.UUID(data.job_id), "google_drive")
        try:
            config = provider.picker_config(ctx)
        except (ProviderError, ReauthRequired) as exc:
            db.commit()  # erneuerte Tokens bzw. needs_reauth der Verbindung behalten
            raise routes._provider_failure(exc) from exc
    except HTTPException as exc:
        raise _ticket_failure(exc, data) from exc
    expires = connection.access_expires_at
    remaining = int((expires - datetime.now(UTC)).total_seconds()) if expires else 0
    try:
        apply_ticket = picker_tickets.issue(picker_tickets.TicketData(
            stage="apply", tenant_id=data.tenant_id, user_id=data.user_id, job_id=data.job_id,
            return_url=data.return_url, issued_at=data.issued_at, session_id=data.session_id,
        ))
    except ValueError as exc:
        # Kette abgelaufen (Ausstellung + 10 min): neu im Wizard öffnen
        raise HTTPException(status_code=404, detail={"code": "ticket_invalid", "message": "ticket_invalid", "params": {}, "return_url": data.return_url}) from exc
    AuditService().log(
        db, action="cloud_import.picker_token", actor=user, entity_type="import_job",
        details={"job_id": str(job.id), "provider": provider.key}, commit=False,
    )
    db.commit()
    return PickerTokenRead(**config, expires_in=max(0, remaining), apply_ticket=apply_ticket, return_url=data.return_url)


@router.post("/cloud-import/picker/google-drive/apply", response_model=PickerApplyRead)
def google_drive_picker_apply(payload: PickerApplyIn, request: Request, response: Response, db: Session = Depends(get_db)):
    """Für die Picker-Seite: gewählte Datei-IDs (nur Dateien, Ordner gibt drive.file nicht frei)
    übernehmen und das Auflisten starten; danach Rücksprung in den Wizard."""
    response.headers.update(_NO_STORE)
    data = _consume(payload, request, "apply")
    try:
        user = _ticket_user(db, data)
        refs = list(dict.fromkeys(payload.file_ids))[:PICKER_MAX_ITEMS]
        if not all(GOOGLE_ID.match(ref) for ref in refs):
            raise routes._http(ImportFailure(422, "invalid_ref"))
        job, _provider, _ctx, _connection = _google_job(db, user, uuid.UUID(data.job_id), "google_drive")
        routes.set_cloud_selection(job.id, routes.SelectionIn(refs=refs), db=db, user=user)
    except HTTPException as exc:
        raise _ticket_failure(exc, data) from exc
    return PickerApplyRead(return_url=data.return_url)


# --- Google Fotos: Picker-Sitzung -------------------------------------------------------------


class PhotosSessionRead(BaseModel):
    picker_uri: str
    poll_seconds: float
    timeout_seconds: float | None = None


@router.post("/cloud-import/jobs/{job_id}/google-photos/session", response_model=PhotosSessionRead)
def google_photos_session(job_id: uuid.UUID, response: Response, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Neue Auswahl in Google Fotos (ersetzt eine angefangene)."""
    require_permission(user, P.FILES_IMPORT)
    enforce_rate_limit(f"cloud-import-photos-session:{user.user_id}", limit=20, period_seconds=600)
    job, provider, ctx, _connection = _google_job(db, user, job_id, "google_photos", lock=True)
    previous = str((job.listing_state or {}).get("picker_session") or "")
    try:
        if previous:
            try:
                provider.delete_session(ctx, previous)
            except ProviderError:
                pass  # Aufräumen ist Zusatz; die Sitzung läuft bei Google ohnehin ab
        session = provider.create_session(ctx)
    except (ProviderError, ReauthRequired) as exc:
        db.commit()
        raise routes._provider_failure(exc) from exc
    job.listing_state = {"picker_session": session.id}
    job.error = None
    connections.touch(_connection)
    db.commit()
    response.headers.update(_NO_STORE)
    return PhotosSessionRead(picker_uri=session.picker_uri, poll_seconds=session.poll_seconds, timeout_seconds=session.timeout_seconds)


class PhotosPollRead(BaseModel):
    done: bool
    poll_seconds: float
    job: routes.ImportJobRead


@router.post("/cloud-import/jobs/{job_id}/google-photos/session/poll", response_model=PhotosPollRead)
def google_photos_poll(job_id: uuid.UUID, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Stand der Auswahl; sobald sie abgeschlossen ist, beginnt das Auflisten (``listing``)."""
    require_permission(user, P.FILES_IMPORT)
    enforce_rate_limit(f"cloud-import-photos-poll:{user.user_id}", limit=600, period_seconds=600)
    job, provider, ctx, _connection = _google_job(db, user, job_id, "google_photos")
    session_id = str((job.listing_state or {}).get("picker_session") or "")
    if not session_id:
        raise routes._http(ImportFailure(409, "photos_session_missing"))
    try:
        status = provider.session_status(ctx, session_id)
    except ProviderError as exc:
        db.commit()
        if exc.code == "not_found":
            # Sitzung abgelaufen oder gelöscht: neu auswählen
            raise routes._http(ImportFailure(409, "photos_session_expired")) from exc
        raise routes._provider_failure(exc) from exc
    except ReauthRequired as exc:
        db.commit()
        raise routes._provider_failure(exc) from exc
    db.commit()
    if not status.media_items_set:
        return PhotosPollRead(done=False, poll_seconds=status.poll_seconds, job=routes._job_read(db, job, user, with_counts=False))
    listed = routes.set_cloud_selection(job.id, routes.SelectionIn(refs=[f"session:{session_id}"]), db=db, user=user)
    return PhotosPollRead(done=True, poll_seconds=status.poll_seconds, job=listed)


# --- Nachbau für den E2E-Stack (nur CLOUD_IMPORT_FAKE_PROVIDERS, main.py bindet es nur dann ein) ---

fake_router = APIRouter()

_FAKE_CSP = "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; form-action 'self'"


def _require_fake() -> None:
    if not providers.fake_mode():
        raise HTTPException(status_code=404)


@fake_router.get("/cloud-import/fake-google/picker.js", response_class=PlainTextResponse)
def fake_google_picker_script():
    """Ersetzt https://apis.google.com/js/api.js im E2E-Stack: dieselbe Schnittstelle
    (gapi.load, google.picker.PickerBuilder …), zeigt die Testablage als einfache Liste."""
    _require_fake()
    from app.services.cloud_import.fake_google import shared_fake

    fake = shared_fake()
    files = [
        {"id": file_id, "name": name, "mimeType": mime}
        for file_id, (name, mime, parent, _content, _sha) in fake.files.items()
        if parent is None and not mime.endswith(".folder")
    ]
    script = _FAKE_PICKER_JS.replace("__FILES__", _json_for_script(files))
    return PlainTextResponse(script, media_type="text/javascript", headers=_NO_STORE)


def _json_for_script(value) -> str:
    import json

    # Kein «</script>»-Ausbruch möglich (wird als eigene Datei geladen, trotzdem maskieren)
    return json.dumps(value).replace("<", "\\u003c")


@fake_router.get("/cloud-import/fake-google/photos/{session_id}", response_class=HTMLResponse)
@fake_router.get("/cloud-import/fake-google/photos/{session_id}/autoclose", response_class=HTMLResponse)
def fake_google_photos_page(session_id: str):
    """Ersetzt die Auswahlseite von Google Fotos im E2E-Stack."""
    _require_fake()
    body = (
        "<!doctype html><html lang=\"de\"><head><meta charset=\"utf-8\"><title>Google Fotos (Test)</title></head><body>"  # i18n-ok: Testseite nur im E2E-Stack
        "<h1>Google Fotos (Test)</h1>"  # i18n-ok: Testseite nur im E2E-Stack
        f"<form method=\"post\" action=\"/api/cloud-import/fake-google/photos/{escape(session_id)}/done\">"
        "<button type=\"submit\">Fertig</button></form></body></html>"  # i18n-ok: Testseite nur im E2E-Stack
    )
    return HTMLResponse(body, headers={**_NO_STORE, "Content-Security-Policy": _FAKE_CSP})


@fake_router.post("/cloud-import/fake-google/photos/{session_id}/done", response_class=HTMLResponse)
def fake_google_photos_done(session_id: str):
    _require_fake()
    from app.services.cloud_import.fake_google import shared_fake

    if not shared_fake().complete(session_id):
        raise HTTPException(status_code=404)
    body = "<!doctype html><html lang=\"de\"><head><meta charset=\"utf-8\"><title>Fertig</title></head><body><p>Auswahl übernommen.</p></body></html>"  # i18n-ok: Testseite nur im E2E-Stack
    return HTMLResponse(body, headers={**_NO_STORE, "Content-Security-Policy": _FAKE_CSP})


_FAKE_PICKER_JS = r"""
// Nachgebauter Google Picker (nur E2E-Stack, CLOUD_IMPORT_FAKE_PROVIDERS).
(function () {
  var FILES = __FILES__;
  function Builder() { this.cb = null; this.max = 200; }
  ["addView", "addViewGroup", "enableFeature", "setOAuthToken", "setDeveloperKey", "setAppId", "setLocale",
   "setOrigin", "setTitle", "setSize"].forEach(function (name) { Builder.prototype[name] = function () { return this; }; });
  Builder.prototype.setMaxItems = function (n) { this.max = n; return this; };
  Builder.prototype.setCallback = function (cb) { this.cb = cb; return this; };
  Builder.prototype.build = function () {
    var cb = this.cb;
    return {
      setVisible: function (visible) {
        var old = document.getElementById("fake-google-picker");
        if (old) old.remove();
        if (!visible) return;
        var box = document.createElement("div");
        box.id = "fake-google-picker";
        box.setAttribute("role", "dialog");
        box.setAttribute("aria-label", "Google Picker (Test)");
        FILES.forEach(function (file) {
          var label = document.createElement("label");
          var input = document.createElement("input");
          input.type = "checkbox";
          input.value = file.id;
          label.appendChild(input);
          label.appendChild(document.createTextNode(" " + file.name));
          box.appendChild(label);
        });
        var pick = document.createElement("button");
        pick.type = "button";
        pick.textContent = "Select";
        pick.onclick = function () {
          var docs = FILES.filter(function (f) {
            return box.querySelector('input[value="' + f.id + '"]').checked;
          }).map(function (f) { return { id: f.id, name: f.name, mimeType: f.mimeType }; });
          box.remove();
          cb({ action: "picked", docs: docs });
        };
        var cancel = document.createElement("button");
        cancel.type = "button";
        cancel.textContent = "Cancel";
        cancel.onclick = function () { box.remove(); cb({ action: "cancel" }); };
        box.appendChild(pick);
        box.appendChild(cancel);
        document.body.appendChild(box);
      },
      dispose: function () {}
    };
  };
  function DocsView() {}
  ["setIncludeFolders", "setSelectFolderEnabled", "setMode", "setEnableDrives", "setOwnedByMe", "setMimeTypes"].forEach(function (name) {
    DocsView.prototype[name] = function () { return this; };
  });
  window.google = window.google || {};
  window.google.picker = {
    PickerBuilder: Builder, DocsView: DocsView,
    ViewId: { DOCS: "all" }, DocsViewMode: { LIST: "list", GRID: "grid" },
    Feature: { MULTISELECT_ENABLED: "multiselect", SUPPORT_DRIVES: "drives" },
    Action: { PICKED: "picked", CANCEL: "cancel", LOADED: "loaded" }
  };
  window.gapi = { load: function (name, cb) { (typeof cb === "function" ? cb : cb.callback)(); } };
})();
"""
