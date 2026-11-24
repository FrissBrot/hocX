"""Editor 1a: Präsenz «wo ist wer» (WS-Fokus, gedrosselt, je Protokoll) und nachträgliche
Bildunterschrift (PATCH /protocol-images/{id}) mit Rechten wie beim Bearbeiten des Blocks."""
from __future__ import annotations

import asyncio
import io
import uuid

import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image
from pydantic import ValidationError
from starlette.datastructures import Headers

from app.api.routes import files as files_routes
from app.api.routes.collaboration_ws import FocusThrottle, parse_focus
from app.core.redis_client import get_redis, get_redis_sync
from app.models import ProtocolImage
from app.schemas.protocol import ProtocolImageCaptionUpdate
from app.services.collaboration_service import CollaborationService, _lock_key
from app.services.file_service import FileService
from tests.factories import (
    make_current_user,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_template,
    make_tenant,
)


# ── Fokus ───────────────────────────────────────────────────────────────────────────────────


def test_parse_focus_validates_ids_and_downgrades_editing_for_readers():
    element = str(uuid.uuid4())
    assert parse_focus({"element_id": element, "block_id": None, "mode": "editing"}, can_edit=True) == (element, None, "editing")
    assert parse_focus({"element_id": element, "mode": "editing"}, can_edit=False) == (element, None, "viewing")
    assert parse_focus({"element_id": "keine-uuid", "mode": "viewing"}, can_edit=True) is None
    assert parse_focus({"element_id": 5, "mode": "viewing"}, can_edit=True) is None
    assert parse_focus({"element_id": element, "mode": "tippen"}, can_edit=True) is None
    assert parse_focus({"element_id": None, "block_id": None, "mode": "viewing"}, can_edit=True) == (None, None, "viewing")


def test_focus_throttle_sends_first_then_latest_per_interval():
    sent: list = []

    async def scenario():
        async def send(value):
            sent.append(value)

        throttle = FocusThrottle(send, interval=0.05)
        await throttle.submit("a")
        await throttle.submit("b")
        await throttle.submit("c")
        await throttle.submit("d")
        await asyncio.sleep(0.12)
        await throttle.submit("d")  # unverändert: nicht erneut
        await throttle.close()

    asyncio.run(scenario())
    assert sent == ["a", "d"]


def test_focus_snapshot_only_for_present_connections():
    async def scenario():
        collab = CollaborationService(get_redis())
        protocol_id = 900_000 + uuid.uuid4().int % 1000
        await collab.join(protocol_id, "c1", 7, "Anna")
        await collab.set_focus(protocol_id, "c1", {"user_id": 7, "display_name": "Anna", "element_id": None, "block_id": None, "mode": "viewing"})
        await collab.set_focus(protocol_id, "verwaist", {"user_id": 8, "display_name": "Ben", "element_id": None, "block_id": None, "mode": "viewing"})
        snapshot = await collab.focus_snapshot(protocol_id)
        other = await collab.focus_snapshot(protocol_id + 1)
        await collab.leave(protocol_id, "c1")
        after_leave = await collab.focus_snapshot(protocol_id)
        await collab.redis.hdel(f"hocx:presence-focus:{protocol_id}", "verwaist")
        return snapshot, other, after_leave

    async def run():
        try:
            return await scenario()
        finally:
            # Gemeinsamer Async-Client: Verbindungen dieses Loops schliessen (wie test_collaboration_locks)
            await get_redis().connection_pool.disconnect()

    snapshot, other, after_leave = asyncio.run(run())
    assert [(entry["connection_id"], entry["user_id"]) for entry in snapshot] == [("c1", 7)]
    assert other == [] and after_leave == []


# ── Bildunterschrift ────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolated_storage_root(monkeypatch, tmp_path):
    from app.core.config import settings

    monkeypatch.setattr(settings, "thumbnail_root", str(tmp_path / "storage-local" / "thumbnails"))


def _png_upload() -> UploadFile:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 24), color=(10, 20, 30)).save(buffer, format="PNG")
    buffer.seek(0)
    return UploadFile(file=buffer, filename="bild.png", headers=Headers({"content-type": "image/png"}))


def _image(db, tenant_id: int, status: str = "geplant"):
    template = make_template(db, tenant_id)
    protocol = make_protocol(db, tenant_id, template.id, status=status)
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(db, element.id, configuration_snapshot_json={})
    image = asyncio.run(FileService().save_protocol_image(db, protocol_element_block=block, file=_png_upload()))
    return protocol, block, db.query(ProtocolImage).filter(ProtocolImage.public_id == image.id).one()


def _status(call) -> int:
    with pytest.raises(HTTPException) as exc_info:
        call()
    return exc_info.value.status_code


def test_caption_can_be_changed_and_cleared(db):
    tenant = make_tenant(db)
    _protocol, _block, image = _image(db, tenant.id)
    writer = make_current_user(tenant.id)
    read = files_routes.patch_image_caption(image.public_id, ProtocolImageCaptionUpdate(caption="  Sonnenuntergang "), db=db, user=writer)
    assert read.caption == "Sonnenuntergang"
    assert db.get(ProtocolImage, image.id).caption == "Sonnenuntergang"
    read = files_routes.patch_image_caption(image.public_id, ProtocolImageCaptionUpdate(caption="   "), db=db, user=writer)
    assert read.caption is None


def test_caption_length_is_limited():
    with pytest.raises(ValidationError):
        ProtocolImageCaptionUpdate(caption="x" * 501)
    assert ProtocolImageCaptionUpdate(caption="x" * 500).caption == "x" * 500


def test_caption_rules_like_block_editing(db):
    tenant = make_tenant(db)
    protocol, block, image = _image(db, tenant.id)
    reader = make_current_user(tenant.id, permissions=frozenset({"meetings.read"}))
    assert _status(lambda: files_routes.patch_image_caption(image.public_id, ProtocolImageCaptionUpdate(caption="x"), db=db, user=reader)) == 403

    # Block von einer anderen Person gesperrt -> 409
    other_editor = make_current_user(tenant.id, user_id=4242)
    redis = get_redis_sync()
    key = _lock_key(protocol.id, f"block-{block.public_id}")
    redis.set(key, '{"user_id": 4242, "display_name": "Andere", "connection_id": "x"}', ex=30)
    try:
        writer = make_current_user(tenant.id)
        assert _status(lambda: files_routes.patch_image_caption(image.public_id, ProtocolImageCaptionUpdate(caption="x"), db=db, user=writer)) == 409
        # Die sperrende Person selbst darf
        files_routes.patch_image_caption(image.public_id, ProtocolImageCaptionUpdate(caption="ok"), db=db, user=other_editor)
    finally:
        redis.delete(key)

    protocol.status = "abgeschlossen"
    db.flush()
    writer = make_current_user(tenant.id)
    assert _status(lambda: files_routes.patch_image_caption(image.public_id, ProtocolImageCaptionUpdate(caption="x"), db=db, user=writer)) == 409


def test_caption_foreign_or_unknown_image_is_404(db):
    owner = make_tenant(db, "Besitzer")
    other = make_tenant(db, "Fremd")
    _protocol, _block, image = _image(db, owner.id)
    attacker = make_current_user(other.id, role="admin")
    assert _status(lambda: files_routes.patch_image_caption(uuid.uuid4(), ProtocolImageCaptionUpdate(caption="x"), db=db, user=attacker)) == 404
    assert _status(lambda: files_routes.patch_image_caption(image.public_id, ProtocolImageCaptionUpdate(caption="x"), db=db, user=attacker)) == 404
    assert db.get(ProtocolImage, image.id).caption is None
