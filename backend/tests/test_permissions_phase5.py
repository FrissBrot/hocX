"""Plan «Berechtigungen», Phase 5: Kontext-Freigaben (Migration 0196, context_visibility_service).

1. Seed: jeder Mandant hat die drei Modul-Standards «nur Rolle» - für bestehende Mandanten wird
   nichts sichtbar, was vorher unsichtbar war.
2. Freigabe «alle Teilnehmenden» + «nur Bilder» für Abgaben: Teilnehmende ohne Rollenrecht sehen
   Abgabe-Bilder, nicht Abgabe-PDFs und nicht Protokoll-Dateien; Inhalt, Vorschau, Download,
   Metadaten und ZIP gleich geschützt; nie Schreibzugriff.
3. Override je Auftrag (auditiert), «nur eigene Einreichungen», Liste «Fotos aus Abgaben».
4. Fremder Mandant 404, ohne Login nichts, RLS der neuen Tabelle.
5. Security-Review Phase 4: Reichweite «nur zugewiesene» gilt auch in Galerie, Suche und Einzelabruf.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.api.routes import context_visibility as visibility_routes
from app.api.routes import files as files_routes
from app.api.routes import search as search_routes
from app.api.routes import submission_assignments as submission_routes
from app.core.security import build_current_user, create_session_token, get_optional_current_user
from app.core.tenant_scope import bind_tenant_scope
from app.models import (
    ContextVisibility,
    GalleryImage,
    ProtocolImage,
    StoredFile,
    SubmissionAssignment,
    SubmissionUpload,
    SubmissionUploadFile,
)
from app.schemas.files import StoredFileTagsUpdate
from app.schemas.role import RoleCreate
from app.schemas.search import GlobalSearchQuery
from app.schemas.submission import SubmissionAssignmentUpdate, SubmissionFileVisibility
from app.services import context_visibility_service as visibility
from app.services import role_service
from app.services.access_service import AccessService
from tests.factories import (
    GRANDFATHERED_FEATURES,
    make_app_user,
    make_event,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_template,
    make_tenant,
)
from tests.test_tenant_rls import as_app

FEATURES = GRANDFATHERED_FEATURES + ("abgabebox",)
access = AccessService()


def _assignment(db, tenant_id: int, title: str, **values) -> SubmissionAssignment:
    values.setdefault("source_type", "manual")
    assignment = SubmissionAssignment(tenant_id=tenant_id, title=title, public_slug=f"a-{uuid.uuid4().hex[:8]}", **values)
    db.add(assignment)
    db.flush()
    return assignment


def _file(db, tenant_id: int, name: str, mime: str) -> StoredFile:
    stored = StoredFile(tenant_id=tenant_id, original_name=name, mime_type=mime, storage_path=f"uploads/{uuid.uuid4().hex}", scan_status="clean")
    db.add(stored)
    db.flush()
    return stored


def _submit(db, assignment: SubmissionAssignment, name: str, mime: str, *, event_id: int | None = None) -> StoredFile:
    upload = SubmissionUpload(assignment_id=assignment.id, status="submitted", event_id=event_id)
    db.add(upload)
    db.flush()
    stored = _file(db, assignment.tenant_id, name, mime)
    db.add(SubmissionUploadFile(upload_id=upload.id, stored_file_id=stored.id, sort_index=0))
    db.flush()
    return stored


def _role(db, actor, name: str, permissions: list[str], scopes: dict[str, str] | None = None):
    role = role_service.create_role(db, actor, RoleCreate(name=name, permissions=permissions, scopes=scopes))
    db.flush()
    return role


def _account(db, email: str, tenant_id: int, role) -> SimpleNamespace:
    account = make_app_user(db, email, tenant_id=tenant_id, role_code="reader")
    role_service.set_user_roles(db, None, account, [role])
    db.flush()
    return account


@pytest.fixture
def org(db):
    tenant = make_tenant(db, "Verein A", features=FEATURES)
    other = make_tenant(db, "Verein B", features=FEATURES)
    admin = make_app_user(db, "admin@a.example", tenant_id=tenant.id, role_code="admin")
    admin_user = build_current_user(db, admin)
    # Teilnehmende ohne Rollenrechte auf Dateien: nur «Sitzungen ansehen»
    member_role = _role(db, admin_user, "Mitglied", ["meetings.read"])
    member = _account(db, "mitglied@a.example", tenant.id, member_role)
    reader = make_app_user(db, "leser@a.example", tenant_id=tenant.id, role_code="reader")

    lager = _assignment(db, tenant.id, "Lager")
    andere = _assignment(db, tenant.id, "Andere")
    lager_photo = _submit(db, lager, "lager-foto.jpg", "image/jpeg")
    lager_pdf = _submit(db, lager, "lager-bericht.pdf", "application/pdf")
    andere_photo = _submit(db, andere, "andere-foto.jpg", "image/jpeg")

    gallery_photo = _file(db, tenant.id, "galerie.jpg", "image/jpeg")
    db.add(GalleryImage(tenant_id=tenant.id, stored_file_id=gallery_photo.id))
    template = make_template(db, tenant.id)
    protocol = make_protocol(db, tenant.id, template.id)  # Entwurf: Mitglieder sehen es nicht
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(db, element.id, {})
    protocol_photo = _file(db, tenant.id, "protokoll.jpg", "image/jpeg")
    db.add(ProtocolImage(protocol_element_block_id=block.id, stored_file_id=protocol_photo.id))
    db.flush()

    other_admin = make_app_user(db, "admin@b.example", tenant_id=other.id, role_code="admin")
    other_member = _account(db, "mitglied@b.example", other.id, _role(db, build_current_user(db, other_admin), "Mitglied", ["meetings.read"]))
    return SimpleNamespace(
        tenant=tenant, other=other, admin=admin, admin_user=admin_user, member=member, reader=reader,
        lager=lager, andere=andere, lager_photo=lager_photo, lager_pdf=lager_pdf, andere_photo=andere_photo,
        gallery_photo=gallery_photo, protocol_photo=protocol_photo, other_member=other_member,
    )


def _user(db, account):
    return build_current_user(db, account)


def _can_read(db, user, stored: StoredFile) -> bool:
    try:
        access.ensure_can_read_stored_file(db, user, stored.id)
    except HTTPException as exc:
        assert exc.status_code in (403, 404)
        return False
    return True


def _share_submissions(db, org, audience="all_participants", file_filter="images"):
    visibility_routes.put_context_visibility(
        "abgabe", visibility_routes.ContextVisibilityWrite(audience=audience, file_filter=file_filter), db=db, user=org.admin_user,
    )


def _status(call) -> HTTPException:
    with pytest.raises(HTTPException) as caught:
        call()
    return caught.value


# ── 1. Seed ─────────────────────────────────────────────────────────────────────────────────


def test_every_tenant_gets_role_only_defaults(db, org):
    rows = db.scalars(select(ContextVisibility).where(ContextVisibility.tenant_id == org.tenant.id)).all()
    assert {(row.module, row.context_id, row.audience, row.file_filter) for row in rows} == {
        ("abgabe", None, "role_only", "images"), ("protokoll", None, "role_only", "all"), ("album", None, "role_only", "all"),
    }
    assert visibility.module_rules(db, org.tenant.id) == visibility.DEFAULTS
    assert visibility.any_submission_grant(db, org.tenant.id) is False


def test_default_seed_changes_nothing(db, org):
    """Standard «nur Rolle»: Mitglieder und Leser sehen keine Datei, die sie vorher nicht sahen."""
    files = [org.lager_photo, org.lager_pdf, org.andere_photo, org.gallery_photo, org.protocol_photo]
    for account in (org.member, org.reader):
        user = _user(db, account)
        assert [_can_read(db, user, stored) for stored in files] == [False] * len(files)
        assert all(not visibility.context_grant_allows(db, user, stored) for stored in files)
        assert db.scalars(visibility.visible_files_query(db, user)).all() == []
    admin = org.admin_user
    assert all(_can_read(db, admin, stored) for stored in files)


# ── 2. Freigabe für alle Teilnehmenden, nur Bilder ──────────────────────────────────────────


def test_participants_see_submission_images_only(db, org):
    _share_submissions(db, org)
    member = _user(db, org.member)
    assert _can_read(db, member, org.lager_photo)
    assert _can_read(db, member, org.andere_photo)
    assert not _can_read(db, member, org.lager_pdf)  # nur Bilder
    assert not _can_read(db, member, org.protocol_photo)  # Protokolle: nur Rolle
    assert not _can_read(db, member, org.gallery_photo)  # Album-Standard bleibt «nur Rolle»
    assert visibility.any_submission_grant(db, org.tenant.id) is True

    page = visibility_routes.list_shared_submission_photos(skip=0, limit=60, db=db, user=member)
    assert page.total == 2
    assert {item.id for item in page.items} == {org.lager_photo.public_id, org.andere_photo.public_id}
    assert {item.assignment_title for item in page.items} == {"Lager", "Andere"}


def test_album_grant(db, org):
    visibility_routes.put_context_visibility(
        "album", visibility_routes.ContextVisibilityWrite(audience="all_participants", file_filter="all"), db=db, user=org.admin_user,
    )
    member = _user(db, org.member)
    assert _can_read(db, member, org.gallery_photo)
    assert not _can_read(db, member, org.lager_photo)
    assert set(db.scalars(visibility.visible_files_query(db, member, module="album"))) == {org.gallery_photo.id}


def test_file_routes_are_protected_alike(db, org, monkeypatch):
    _share_submissions(db, org)
    member = _user(db, org.member)
    pdf = org.lager_pdf.public_id
    for call in (
        lambda: files_routes.get_stored_file_content(pdf, request=None, db=db, user=member),
        lambda: files_routes.get_stored_file_thumbnail(pdf, db=db, user=member),
        lambda: files_routes.download_stored_file(pdf, request=None, part="image", db=db, user=member),
        lambda: files_routes.get_stored_file_metadata(pdf, db=db, user=member),
    ):
        assert _status(call).status_code == 403
    # Freigegebenes Bild: die Zugriffsprüfung lässt durch (Vorschau fehlt nur im Test-Speicher)
    monkeypatch.setattr(files_routes.service, "ensure_thumbnail", lambda *args, **kwargs: None)
    error = _status(lambda: files_routes.get_stored_file_thumbnail(org.lager_photo.public_id, db=db, user=member))
    assert (error.status_code, error.detail) == (404, "Keine Vorschau verfügbar")
    # ZIP eines Auftrags verlangt weiterhin submissions.read
    assert _status(lambda: submission_routes.download_all_files_zip(org.lager.public_id, db=db, user=member)).status_code == 403
    # Abgabe-Routen bleiben beim Rollenrecht
    assert _status(lambda: submission_routes.list_elements(org.lager.public_id, db=db, user=member)).status_code == 403


def test_grant_never_allows_writes(db, org):
    _share_submissions(db, org)
    member = _user(db, org.member)
    photo = org.lager_photo.public_id
    assert _status(lambda: files_routes.update_stored_file_tags(photo, StoredFileTagsUpdate(tags=["x"]), db=db, user=member)).status_code == 403
    # Öffentlich teilen (öffentliche Ableitung) geht nur mit Rollenrechten
    from app.api.routes import share_links
    from app.schemas.files import ShareLinkCreate

    payload = ShareLinkCreate(name="Link", file_ids=[photo])
    assert _status(lambda: share_links.create_share_link(payload, db=db, user=member)).status_code == 403


# ── 3. Override je Auftrag, eigene Einreichungen ────────────────────────────────────────────


def _audit_rows(db, tenant_id: int):
    return db.execute(
        text("SELECT entity_type, details_json FROM audit_log WHERE tenant_id = :t AND action = 'context_visibility.changed' ORDER BY id"),
        {"t": tenant_id},
    ).all()


def test_override_per_assignment(db, org):
    member = _user(db, org.member)
    custom = SubmissionFileVisibility(mode="custom", audience="all_participants", file_filter="all")
    read = submission_routes.patch_assignment(org.lager.public_id, SubmissionAssignmentUpdate(file_visibility=custom), db=db, user=org.admin_user)
    assert read.file_visibility == custom
    assert _can_read(db, member, org.lager_pdf)  # Override: alle Dateitypen
    assert _can_read(db, member, org.lager_photo)
    assert not _can_read(db, member, org.andere_photo)  # Standard: nur Rolle
    listed = submission_routes.list_assignments(db=db, user=org.admin_user)
    assert {item.title: item.file_visibility.mode for item in listed} == {"Lager": "custom", "Andere": "default"}

    submission_routes.patch_assignment(
        org.lager.public_id, SubmissionAssignmentUpdate(file_visibility=SubmissionFileVisibility(mode="default")), db=db, user=org.admin_user,
    )
    assert not _can_read(db, member, org.lager_pdf)

    rows = _audit_rows(db, org.tenant.id)
    assert [(row.entity_type, row.details_json["before"], row.details_json["after"]) for row in rows] == [
        ("submission_assignment", "default", {"audience": "all_participants", "file_filter": "all"}),
        ("submission_assignment", {"audience": "all_participants", "file_filter": "all"}, "default"),
    ]


def test_module_change_is_audited_with_before_and_after(db, org):
    _share_submissions(db, org, file_filter="all")
    _share_submissions(db, org, file_filter="all")  # unverändert: kein zweiter Eintrag
    [row] = _audit_rows(db, org.tenant.id)
    assert row.details_json == {
        "module": "abgabe", "before": {"audience": "role_only", "file_filter": "images"}, "after": {"audience": "all_participants", "file_filter": "all"},
    }


def test_own_submissions_only(db, org):
    other_person = make_app_user(db, "andere@a.example", tenant_id=org.tenant.id, role_code="reader")
    camp = _assignment(db, org.tenant.id, "Berichte", source_type="events", tag_filter="lager", responsible_participant_source="spezial1_ids")
    mine_event = make_event(db, org.tenant.id, title="Lager 1")
    theirs_event = make_event(db, org.tenant.id, title="Lager 2")
    mine_event.tag, mine_event.spezial1_ids = "lager", [org.member.id]
    theirs_event.tag, theirs_event.spezial1_ids = "lager", [other_person.id]
    db.flush()
    mine = _submit(db, camp, "meins.jpg", "image/jpeg", event_id=mine_event.id)
    theirs = _submit(db, camp, "fremd.jpg", "image/jpeg", event_id=theirs_event.id)
    mine_pdf = _submit(db, camp, "meins.pdf", "application/pdf", event_id=mine_event.id)
    submission_routes.patch_assignment(
        camp.public_id,
        SubmissionAssignmentUpdate(file_visibility=SubmissionFileVisibility(mode="custom", audience="own_submissions", file_filter="images")),
        db=db, user=org.admin_user,
    )
    member = _user(db, org.member)
    assert _can_read(db, member, mine)
    assert not _can_read(db, member, theirs)
    assert not _can_read(db, member, mine_pdf)
    assert set(db.scalars(visibility.visible_files_query(db, member))) == {mine.id}

    # Zurückgezogen = nicht mehr freigegeben
    db.execute(text("UPDATE submission_upload_file SET withdrawn_at = now() WHERE stored_file_id = :id"), {"id": mine.id})
    assert not _can_read(db, member, mine)


# ── 4. Fremder Mandant, ohne Login, RLS ─────────────────────────────────────────────────────


def test_foreign_tenant_gets_404(db, org):
    _share_submissions(db, org)
    foreign = _user(db, org.other_member)
    assert not visibility.context_grant_allows(db, foreign, org.lager_photo)
    photo_id = org.lager_photo.public_id  # unter RLS ist die Zeile für Verein B unsichtbar
    with as_app(db, org.other.id):
        error = _status(lambda: files_routes.get_stored_file_thumbnail(photo_id, db=db, user=foreign))
        assert error.status_code == 404
        page = visibility_routes.list_shared_submission_photos(skip=0, limit=60, db=db, user=foreign)
        assert page.total == 0


def test_participant_without_login_gets_no_session(db, org):
    _share_submissions(db, org)
    org.member.login_enabled = False
    db.flush()
    try:
        assert get_optional_current_user(SimpleNamespace(cookies={}), db, create_session_token(org.member.id)) is None
    finally:
        bind_tenant_scope(db, None)


def test_context_visibility_rls(db, org):
    with as_app(db, org.other.id):
        visible = db.scalar(select(func.count()).select_from(ContextVisibility).where(ContextVisibility.tenant_id == org.tenant.id))
        assert visible == 0
        with pytest.raises(DBAPIError):
            with db.begin_nested():
                db.execute(
                    text("INSERT INTO context_visibility (tenant_id, module, audience) VALUES (:t, 'album', 'all_participants')"),
                    {"t": org.tenant.id},
                )


def test_override_requires_same_tenant_assignment(db, org):
    """Mandantengleicher Fremdschlüssel: kein Override auf einen Auftrag eines anderen Mandanten."""
    foreign = _assignment(db, org.other.id, "Fremd")
    with pytest.raises(DBAPIError):
        with db.begin_nested():
            db.add(ContextVisibility(tenant_id=org.tenant.id, module="abgabe", context_id=foreign.id, audience="all_participants", file_filter="all"))
            db.flush()


def test_invalid_rules_are_rejected():
    with pytest.raises(ValueError):
        visibility.validate("protokoll", visibility.Rule("all_participants", "all"))
    with pytest.raises(ValueError):
        visibility.validate("album", visibility.Rule("own_submissions", "all"))
    with pytest.raises(ValueError):
        visibility.validate("album", visibility.Rule("all_participants", "all"), override=True)


def test_settings_require_settings_manage(db, org):
    member = _user(db, org.member)
    assert _status(lambda: visibility_routes.get_context_visibility(db=db, user=member)).status_code == 403
    write = visibility_routes.ContextVisibilityWrite(audience="all_participants", file_filter="all")
    assert _status(lambda: visibility_routes.put_context_visibility("abgabe", write, db=db, user=member)).status_code == 403
    modules = visibility_routes.get_context_visibility(db=db, user=org.admin_user)
    assert [(item.module, item.fixed) for item in modules] == [("abgabe", False), ("protokoll", True), ("album", False)]


# ── 5. Reichweite «nur zugewiesene» ausserhalb der Abgabe-Routen (Security-Review Phase 4) ──


def _gallery(db, user):
    return files_routes.list_files(
        skip=0, limit=60, source=None, album_id=None, exclude_album_id=None, share_pending=None, only_images=True, exclude_images=False,
        search=None, tags=None, sort_by="created_at", sort_dir="desc", date_from=None, date_to=None, db=db, user=user,
    )


def test_assigned_reviewer_sees_only_assigned_submission_photos(db, org):
    reviewer_role = _role(db, org.admin_user, "Prüfer", ["submissions.review", "photos.read", "meetings.read"], {"submissions.review": "assigned"})
    reviewer = _account(db, "pruefer@a.example", org.tenant.id, reviewer_role)
    submission_routes.patch_assignment(org.lager.public_id, SubmissionAssignmentUpdate(reviewer_ids=[reviewer.public_id]), db=db, user=org.admin_user)
    user = _user(db, reviewer)

    names = {item.original_name for item in _gallery(db, user)}
    assert "lager-foto.jpg" in names and "galerie.jpg" in names
    assert "andere-foto.jpg" not in names
    def timeline_total(viewer):
        return sum(day.count for day in files_routes.files_timeline(only_images=True, search=None, tags=None, sort_dir="desc", db=db, user=viewer))

    assert timeline_total(user) == timeline_total(org.admin_user) - 1
    found = {item.name for item in search_routes.global_search(GlobalSearchQuery.model_construct(q="foto"), db=db, user=user).files}
    assert "lager-foto.jpg" in found and "andere-foto.jpg" not in found

    assert _can_read(db, user, org.lager_photo)
    error = _status(lambda: access.ensure_can_read_stored_file(db, user, org.andere_photo.id))
    assert (error.status_code, error.detail) == (404, "Stored file not found")
    error = _status(lambda: files_routes.get_stored_file_thumbnail(org.andere_photo.public_id, db=db, user=user))
    assert error.status_code == 404

    # Kontext-Freigabe wirkt zusätzlich (additiv)
    _share_submissions(db, org)
    assert _can_read(db, user, org.andere_photo)


def test_reviewer_scope_also_limits_tags_stats_and_album_overview(db, org):
    from app.models.entities import PhotoAlbum, PhotoAlbumItem

    reviewer_role = _role(db, org.admin_user, "Prüfer", ["submissions.review", "photos.read", "files.read", "meetings.read"], {"submissions.review": "assigned"})
    reviewer = _account(db, "pruefer-tags@a.example", org.tenant.id, reviewer_role)
    submission_routes.patch_assignment(org.lager.public_id, SubmissionAssignmentUpdate(reviewer_ids=[reviewer.public_id]), db=db, user=org.admin_user)
    org.andere_photo.tags = ["geheimer-tag"]
    org.lager_photo.tags = ["lager-tag"]
    album = PhotoAlbum(tenant_id=org.tenant.id, name="Gemischt")
    db.add(album)
    db.flush()
    db.add_all([PhotoAlbumItem(album_id=album.id, file_id=org.lager_photo.public_id), PhotoAlbumItem(album_id=album.id, file_id=org.andere_photo.public_id)])
    db.flush()
    user = _user(db, reviewer)

    def tags(viewer):
        return set(files_routes.list_file_tags(query=None, limit=200, db=db, user=viewer))

    assert {"geheimer-tag", "lager-tag"} <= tags(org.admin_user)
    assert "lager-tag" in tags(user) and "geheimer-tag" not in tags(user)

    stats_admin = files_routes.get_file_stats(db=db, user=org.admin_user)
    stats_user = files_routes.get_file_stats(db=db, user=user)
    assert stats_user.photo_count == stats_admin.photo_count - 1

    def album_count(viewer):
        return next(entry.photo_count for entry in files_routes.list_albums(db=db, user=viewer) if entry.id == album.id)

    assert album_count(org.admin_user) == 2
    assert album_count(user) == 1

    hidden = PhotoAlbum(tenant_id=org.tenant.id, name="Abgabe: Andere", kind="submission", submission_assignment_id=org.andere.id)
    db.add(hidden)
    db.flush()
    assert hidden.id in {entry.id for entry in files_routes.list_albums(db=db, user=org.admin_user)}
    assert hidden.id not in {entry.id for entry in files_routes.list_albums(db=db, user=user)}

    # Hinweis «noch nicht freigegeben» geteilter Alben: Auftragstitel/-fotos ebenso ausgeblendet
    from app.models.entities import PhotoAlbumTenantShare

    db.add_all([
        PhotoAlbumItem(album_id=hidden.id, file_id=org.andere_photo.public_id, share_pending=True),
        PhotoAlbumItem(album_id=album.id, file_id=uuid.uuid4(), share_pending=True),
        PhotoAlbumTenantShare(album_id=hidden.id, tenant_id=org.other.id, status="pending"),
        PhotoAlbumTenantShare(album_id=album.id, tenant_id=org.other.id, status="pending"),
    ])
    db.flush()

    def pending(viewer):
        return {row.album_id: row.pending_count for row in files_routes.list_album_pending_releases(db=db, user=viewer)}

    assert pending(org.admin_user) == {hidden.id: 1, album.id: 1}
    assert pending(user) == {album.id: 1}


def test_unrestricted_accounts_lose_nothing(db, org):
    photos_only = _account(db, "fotos@a.example", org.tenant.id, _role(db, org.admin_user, "Fotos", ["photos.read", "meetings.read"]))
    for user in (org.admin_user, _user(db, photos_only)):
        names = {item.original_name for item in _gallery(db, user)}
        assert {"lager-foto.jpg", "andere-foto.jpg", "galerie.jpg"} <= names
        assert _can_read(db, user, org.andere_photo)


# ── 6. Security-Review Phase 5 ──────────────────────────────────────────────────────────────


def test_album_grant_covers_only_gallery_photos(db, org):
    """gallery_image enthält auch Ablage-Dokumente und Direkt-Uploads zu Abgaben: die Album-Freigabe
    gilt nur für Galerie-Fotos ohne Abgabe-Bezug."""
    document = _file(db, org.tenant.id, "ablage.pdf", "application/pdf")
    linked = _file(db, org.tenant.id, "abgabe-direkt.jpg", "image/jpeg")
    withdrawn = _file(db, org.tenant.id, "zurueckgezogen.jpg", "image/jpeg")
    db.add_all([
        GalleryImage(tenant_id=org.tenant.id, stored_file_id=document.id),
        GalleryImage(tenant_id=org.tenant.id, stored_file_id=linked.id, submission_assignment_id=org.lager.id, submission_element_ref="manual"),
        GalleryImage(
            tenant_id=org.tenant.id, stored_file_id=withdrawn.id, submission_assignment_id=org.andere.id, submission_element_ref="manual",
            submission_withdrawn_at=func.now(),
        ),
    ])
    db.flush()
    visibility_routes.put_context_visibility(
        "album", visibility_routes.ContextVisibilityWrite(audience="all_participants", file_filter="all"), db=db, user=org.admin_user,
    )
    member = _user(db, org.member)
    assert _can_read(db, member, org.gallery_photo)
    assert not _can_read(db, member, document)
    assert not _can_read(db, member, linked)  # Abgabe «Lager» steht auf nur Rolle
    assert set(db.scalars(visibility.visible_files_query(db, member, module="album"))) == {org.gallery_photo.id}
    # Abgabe-Freigabe: der Direkt-Upload wird sichtbar, der zurückgezogene nicht
    _share_submissions(db, org)
    assert _can_read(db, member, linked)
    assert not _can_read(db, member, withdrawn)


def test_grant_does_not_open_write_or_clip_paths(db, org):
    from app.schemas.files import FileBulkTagsUpdate

    reviewer_role = _role(
        db, org.admin_user, "Fotoprüfer", ["submissions.review", "photos.manage", "meetings.read"], {"submissions.review": "assigned"},
    )
    reviewer = _account(db, "fotopruefer@a.example", org.tenant.id, reviewer_role)
    _share_submissions(db, org)
    user = _user(db, reviewer)
    andere = org.andere_photo.public_id
    assert _can_read(db, user, org.andere_photo)  # lesen über die Freigabe
    # Schreiben nie über die Freigabe: nicht zugewiesener Auftrag bleibt 404
    assert _status(lambda: files_routes.update_stored_file_tags(andere, StoredFileTagsUpdate(tags=["x"]), db=db, user=user)).status_code == 404
    bulk = FileBulkTagsUpdate(file_ids=[andere], add_tags=["x"], remove_tags=[])
    assert _status(lambda: files_routes.bulk_update_file_tags(bulk, db=db, user=user)).status_code == 404
    # Live-Clip/ZIP nur mit Rollenrechten
    member = _user(db, org.member)
    for part in ("video", "both"):
        error = _status(lambda: files_routes.download_stored_file(org.lager_photo.public_id, request=None, part=part, db=db, user=member))
        assert error.status_code in (403, 404)
