"""Row-Level-Security der Mandantendaten (Migration 0132_tenant_rls, app/core/tenant_scope.py).

Die Testdatenbank läuft als Superuser, der jede Policy umgeht. Diese Tests wechseln deshalb
innerhalb der Testtransaktion per SET LOCAL ROLE auf die Laufzeitrolle hocx_app, wie das Backend
in Produktion. Die übrige Suite prüft dieselben Policies im RLS-Testmodus (tests/conftest.py,
HOCX_TEST_RLS=1) gegen alle Routen."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.db import engine
from app.core.security import create_session_token, get_optional_current_user
from app.core.tenant_scope import bind_tenant_scope, bound_tenant_id, tenant_scope_suspended
from app.models.entities import DocumentTemplate, PhotoAlbum, PhotoAlbumTenantShare, ProtocolTodo, StoredFile, Template
from app.services.user_service import UserService
from tests.factories import (
    make_app_user,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_protocol_todo,
    make_template,
    make_tenant,
)

# Plattformdaten bzw. öffentliche DNS-Daten ohne RLS - siehe Docstring der Migration 0132.
TABLES_WITHOUT_RLS = {"audit_log", "system_error_log", "tenant_charge", "tenant_domain"}


@contextmanager
def as_app(db: Session, tenant_id: int | None):
    """Führt den Block als hocx_app aus, gebunden an `tenant_id` (None: ohne Mandant)."""
    db.flush()
    db.expire_all()
    db.execute(text("SET LOCAL ROLE hocx_app"))
    bind_tenant_scope(db, tenant_id)
    try:
        yield
    finally:
        bind_tenant_scope(db, None)
        db.execute(text("RESET ROLE"))
        db.expire_all()


def _stored_file(db: Session, tenant_id: int, name: str = "foto.png") -> StoredFile:
    stored_file = StoredFile(tenant_id=tenant_id, original_name=name, mime_type="image/png", storage_path=f"uploads/{name}")
    db.add(stored_file)
    db.flush()
    return stored_file


def _visible_ids(db: Session, model, ids) -> set:
    return set(db.scalars(select(model.id).where(model.id.in_(list(ids)))))


def test_every_table_with_tenant_id_has_row_level_security(db):
    rows = db.execute(
        text(
            """
            SELECT c.relname, c.relrowsecurity
              FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
              JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'tenant_id' AND NOT a.attisdropped
             WHERE c.relkind = 'r'
            """
        )
    ).all()
    without_rls = {name for name, enabled in rows if not enabled}
    assert without_rls == TABLES_WITHOUT_RLS
    assert len(rows) > len(TABLES_WITHOUT_RLS)


def test_scope_limits_reads_to_the_bound_tenant(db):
    tenant_a, tenant_b = make_tenant(db), make_tenant(db)
    template_a, template_b = make_template(db, tenant_a.id), make_template(db, tenant_b.id)
    ids = {template_a.id, template_b.id}

    with as_app(db, tenant_a.id):
        assert _visible_ids(db, Template, ids) == {template_a.id}
    with as_app(db, tenant_b.id):
        assert _visible_ids(db, Template, ids) == {template_b.id}
    # Ohne gebundenen Mandanten (Plattform, Hintergrundjobs) bleibt alles sichtbar.
    with as_app(db, None):
        assert _visible_ids(db, Template, ids) == ids


def test_scope_rejects_writes_into_another_tenant(db):
    tenant_a, tenant_b = make_tenant(db), make_tenant(db)
    template_b_id = make_template(db, tenant_b.id, name="Fremd").id
    tenant_b_id = tenant_b.id

    with as_app(db, tenant_a.id):
        updated = db.execute(text("UPDATE template SET name = 'übernommen' WHERE id = :id"), {"id": template_b_id}).rowcount
        assert updated == 0
        with pytest.raises(DBAPIError, match="row-level security"):
            with db.begin_nested():
                db.add(Template(tenant_id=tenant_b_id, name="Eingeschleust"))
                db.flush()

    assert db.scalar(select(Template.name).where(Template.id == template_b_id)) == "Fremd"


def test_protocol_todos_follow_their_protocol(db):
    tenant_a, tenant_b = make_tenant(db), make_tenant(db)
    protocol_a = make_protocol(db, tenant_a.id, make_template(db, tenant_a.id).id)
    block_a = make_protocol_element_block(db, make_protocol_element(db, protocol_a.id).id, configuration_snapshot_json={})
    todo_id = make_protocol_todo(db, block_a.id, task="Im Protokoll").id
    block_a_id = block_a.id
    status_id = db.scalar(select(ProtocolTodo.todo_status_id).where(ProtocolTodo.id == todo_id))
    # tenant_id setzt die Datenbank aus dem Protokoll (Migration 0131_todo_tenant_id).
    assert db.scalar(select(ProtocolTodo.tenant_id).where(ProtocolTodo.id == todo_id)) == tenant_a.id

    with as_app(db, tenant_a.id):
        assert _visible_ids(db, ProtocolTodo, {todo_id}) == {todo_id}
        db.add(ProtocolTodo(protocol_element_block_id=block_a_id, task="Neu", todo_status_id=status_id, sort_index=10))
        db.flush()
    with as_app(db, tenant_b.id):
        assert _visible_ids(db, ProtocolTodo, {todo_id}) == set()
        with pytest.raises(DBAPIError, match="row-level security"):
            with db.begin_nested():
                db.add(ProtocolTodo(protocol_element_block_id=block_a_id, task="Eingeschleust", todo_status_id=status_id, sort_index=11))
                db.flush()


def test_system_document_templates_stay_readable_but_not_writable(db):
    tenant = make_tenant(db)
    system_count = db.scalar(select(DocumentTemplate.id).where(DocumentTemplate.tenant_id.is_(None)).limit(1))

    with as_app(db, tenant.id):
        if system_count is not None:
            assert db.scalar(select(DocumentTemplate.id).where(DocumentTemplate.tenant_id.is_(None)).limit(1)) is not None
        with pytest.raises(DBAPIError, match="row-level security"):
            with db.begin_nested():
                db.add(DocumentTemplate(tenant_id=None, name="Global", document_type="letter"))
                db.flush()


def test_shared_album_is_visible_to_the_partner_and_photos_only_after_accepting(db):
    owner, partner, stranger = make_tenant(db), make_tenant(db), make_tenant(db)
    album = PhotoAlbum(tenant_id=owner.id, name="Sommerlager", kind="manual")
    db.add(album)
    db.flush()
    owner_photo = _stored_file(db, owner.id, "owner.png")
    partner_photo = _stored_file(db, partner.id, "partner.png")
    stranger_photo = _stored_file(db, stranger.id, "stranger.png")
    photo_ids = {owner_photo.id, partner_photo.id, stranger_photo.id}
    owner_photo_id, partner_photo_id, stranger_photo_id = owner_photo.id, partner_photo.id, stranger_photo.id
    album_id = album.id
    owner_id, partner_id, stranger_id = owner.id, partner.id, stranger.id
    db.add(PhotoAlbumTenantShare(album_id=album_id, tenant_id=partner_id, status="pending"))
    db.flush()

    with as_app(db, partner_id):
        # Offene Einladung: Album (Name in der Einladungsliste) ja, Fotos des Besitzers nein.
        assert _visible_ids(db, PhotoAlbum, {album_id}) == {album_id}
        assert _visible_ids(db, StoredFile, photo_ids) == {partner_photo_id}
        db.execute(
            text("UPDATE photo_album_tenant_share SET status = 'accepted' WHERE album_id = :album AND tenant_id = :tenant"),
            {"album": album_id, "tenant": partner_id},
        )

    with as_app(db, partner_id):
        assert _visible_ids(db, StoredFile, photo_ids) == {owner_photo_id, partner_photo_id}
    with as_app(db, owner_id):
        assert _visible_ids(db, StoredFile, photo_ids) == {owner_photo_id, partner_photo_id}
        assert db.scalar(select(PhotoAlbumTenantShare.status).where(PhotoAlbumTenantShare.album_id == album_id)) == "accepted"
    with as_app(db, stranger_id):
        assert _visible_ids(db, PhotoAlbum, {album_id}) == set()
        assert _visible_ids(db, StoredFile, photo_ids) == {stranger_photo_id}
        assert db.scalars(select(PhotoAlbumTenantShare.album_id).where(PhotoAlbumTenantShare.album_id == album_id)).all() == []


def test_partners_of_the_same_album_see_each_others_photos(db):
    owner, partner_a, partner_b = make_tenant(db), make_tenant(db), make_tenant(db)
    album = PhotoAlbum(tenant_id=owner.id, name="Gemeinsam", kind="manual")
    db.add(album)
    db.flush()
    photo_a_id = _stored_file(db, partner_a.id, "a.png").id
    photo_b_id = _stored_file(db, partner_b.id, "b.png").id
    db.add_all(
        [
            PhotoAlbumTenantShare(album_id=album.id, tenant_id=partner_a.id, status="accepted"),
            PhotoAlbumTenantShare(album_id=album.id, tenant_id=partner_b.id, status="accepted", share_location=False),
        ]
    )
    db.flush()

    album_id, partner_a_id, partner_b_id = album.id, partner_a.id, partner_b.id

    with as_app(db, partner_a_id):
        assert _visible_ids(db, StoredFile, {photo_a_id, photo_b_id}) == {photo_a_id, photo_b_id}
        # Schalter der anderen Partner (Standort, öffentliche Links) sind lesbar ...
        assert set(db.scalars(select(PhotoAlbumTenantShare.tenant_id).where(PhotoAlbumTenantShare.album_id == album_id))) == {
            partner_a_id,
            partner_b_id,
        }
        # ... aber nur die eigene Freigabe ist änderbar, fremde Fotos gar nicht.
        updated = db.execute(
            text("UPDATE photo_album_tenant_share SET share_location = true WHERE album_id = :album AND tenant_id = :tenant"),
            {"album": album_id, "tenant": partner_b_id},
        ).rowcount
        assert updated == 0
        renamed = db.execute(text("UPDATE stored_file SET original_name = 'x' WHERE id = :id"), {"id": photo_b_id}).rowcount
        assert renamed == 0


def test_only_the_album_owner_can_invite_partners(db):
    owner, partner, stranger = make_tenant(db), make_tenant(db), make_tenant(db)
    album = PhotoAlbum(tenant_id=owner.id, name="Album", kind="manual")
    db.add(album)
    db.flush()
    album_id, owner_id, partner_id, stranger_id = album.id, owner.id, partner.id, stranger.id

    with as_app(db, stranger_id):
        with pytest.raises(DBAPIError, match="row-level security"):
            with db.begin_nested():
                db.add(PhotoAlbumTenantShare(album_id=album_id, tenant_id=partner_id))
                db.flush()
    with as_app(db, owner_id):
        db.add(PhotoAlbumTenantShare(album_id=album_id, tenant_id=partner_id))
        db.flush()


def test_login_email_check_still_sees_accounts_of_other_tenants(db):
    tenant_a, tenant_b = make_tenant(db), make_tenant(db)
    make_app_user(db, email="belegt@rls.test", tenant_id=tenant_b.id)

    with as_app(db, tenant_a.id):
        with pytest.raises(HTTPException) as exc_info:
            UserService().ensure_login_email_available(db, "belegt@rls.test")
        assert exc_info.value.status_code == 409
        assert bound_tenant_id(db) == tenant_a.id
        assert db.scalar(text("SELECT current_setting('app.tenant_id', true)")) == str(tenant_a.id)


def test_suspending_the_scope_restores_it_afterwards(db):
    tenant = make_tenant(db)
    bind_tenant_scope(db, tenant.id)
    try:
        with tenant_scope_suspended(db):
            assert bound_tenant_id(db) is None
            assert db.scalar(text("SELECT current_setting('app.tenant_id', true)")) == ""
        assert db.scalar(text("SELECT current_setting('app.tenant_id', true)")) == str(tenant.id)
    finally:
        bind_tenant_scope(db, None)


def test_authenticated_request_binds_the_session_to_the_users_tenant(db):
    user = make_app_user(db, email="rls-session@rls.test", role_code="reader")
    request = SimpleNamespace(cookies={})

    current = get_optional_current_user(request, db, create_session_token(user.id))
    try:
        assert current is not None
        assert bound_tenant_id(db) == user.tenant_id
        assert db.scalar(text("SELECT current_setting('app.tenant_id', true)")) == str(user.tenant_id)
    finally:
        bind_tenant_scope(db, None)


def test_scope_is_reapplied_after_commit_and_never_leaks_into_the_pool():
    """Echte Session ohne Test-Savepoints: set_config(..., true) endet mit jeder Transaktion; der
    after_begin-Hook setzt den Mandanten in der nächsten neu."""
    session = Session(bind=engine, autoflush=False, future=True)
    try:
        bind_tenant_scope(session, 4242)
        assert session.scalar(text("SELECT current_setting('app.tenant_id', true)")) == "4242"
        session.commit()
        assert session.scalar(text("SELECT current_setting('app.tenant_id', true)")) == "4242"
        session.rollback()
    finally:
        session.close()

    fresh = Session(bind=engine, autoflush=False, future=True)
    try:
        assert fresh.scalar(text("SELECT current_setting('app.tenant_id', true)")) in (None, "")
    finally:
        fresh.close()
