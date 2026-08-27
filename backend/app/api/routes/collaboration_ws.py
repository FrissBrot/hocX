from __future__ import annotations

import asyncio
import json
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.redis_client import get_redis
from app.core.security import (
    CurrentUser,
    _has_active_mfa_factor,
    _requires_mfa,
    build_current_user,
    parse_session_token,
)
from app.models import AppUser, ListDefinition, Protocol
from app.services import list_snapshot_service, public_id_service
from app.services.access_service import AccessService
from app.services.collaboration_service import CollaborationService
from app.services.protocol_service import ProtocolService

router = APIRouter()
access_service = AccessService()
protocol_service = ProtocolService()

# How often each connection re-checks whether a list it references changed, as a
# reliable fallback/primary mechanism for the "Daten aktualisieren" live hint (see
# poll_list_versions below for why this exists instead of relying on a Redis push).
LIST_VERSION_POLL_INTERVAL_SECONDS = 15


def _authenticate(token: str | None) -> CurrentUser | None:
    session_data = parse_session_token(token)
    if session_data is None:
        return None
    db = SessionLocal()
    try:
        user = db.get(AppUser, int(session_data["user_id"]))
        if user is None or not user.is_active:
            return None
        if user.session_revoke_at is not None:
            token_iat = int(session_data.get("iat", 0))
            if int(user.session_revoke_at.timestamp()) > token_iat:
                return None
        current_user = build_current_user(db, user, session_data.get("tenant_id"), mfa_verified=bool(session_data.get("mfa")))
        # Mirrors get_optional_current_user's MFA enforcement (audit finding, 2026-08-25) -
        # without this, a user who becomes MFA-required (promoted to admin) or whose only
        # factor is administratively deleted keeps full read/write WebSocket access with
        # their existing cookie even though the REST path now correctly locks them out.
        has_mfa_factor = _has_active_mfa_factor(db, user.id)
        if has_mfa_factor and not current_user.mfa_verified:
            return None
        if _requires_mfa(current_user) and (not has_mfa_factor or not current_user.mfa_verified):
            return None
        return current_user
    finally:
        db.close()


def _load_and_authorize(protocol_public_id: uuid.UUID, user: CurrentUser) -> int | None:
    """Resolves the client-supplied public protocol id to its internal id and checks
    read access, in one DB session - returns the internal id on success, None if the
    protocol doesn't exist, isn't in the caller's tenant, or isn't readable by them (all
    three collapse to the same 4403 close code, matching this handler's existing
    behavior before the public_id migration)."""
    db = SessionLocal()
    try:
        protocol_id = public_id_service.resolve_internal_id(db, Protocol, protocol_public_id, tenant_id=user.current_tenant_id)
        if protocol_id is None:
            return None
        if not access_service.can_read_protocol(db, user, protocol_id):
            return None
        return protocol_id
    finally:
        db.close()


def _public_user_id_map(user_ids: set[int]) -> dict[int, uuid.UUID]:
    db = SessionLocal()
    try:
        return public_id_service.resolve_public_ids(db, AppUser, list(user_ids))
    finally:
        db.close()


def _public_list_id_map(list_ids: set[int]) -> dict[int, uuid.UUID]:
    db = SessionLocal()
    try:
        return public_id_service.resolve_public_ids(db, ListDefinition, list(list_ids))
    finally:
        db.close()


def _can_edit(user: CurrentUser) -> bool:
    return user.current_role in {"writer", "admin"}


def _referenced_list_ids(protocol_id: int) -> set[int]:
    db = SessionLocal()
    try:
        return list_snapshot_service.referenced_list_definition_ids(db, protocol_id)
    finally:
        db.close()


def _list_content_versions(list_ids: set[int]) -> dict[int, int]:
    if not list_ids:
        return {}
    db = SessionLocal()
    try:
        rows = db.execute(
            select(ListDefinition.id, ListDefinition.content_version).where(ListDefinition.id.in_(list_ids))
        ).all()
        return {row.id: row.content_version for row in rows}
    finally:
        db.close()


def _origin_allowed(websocket: WebSocket) -> bool:
    # Mirrors main.py's CORSMiddleware allowlist - the WS handshake otherwise relied only
    # on the SameSite=Lax session cookie with no Origin check of its own (audit finding,
    # 2026-08-25). Defensive: this is a same-site collaboration channel with no state-
    # changing side effect a bare cross-origin page load could trigger, but it does allow
    # writing field locks/patches once connected, so it's worth closing regardless.
    origin = websocket.headers.get("origin")
    if not origin:
        return False
    allowed = {o for o in (
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        f"https://{settings.traefik_domain}" if settings.traefik_domain else None,
    ) if o}
    return origin in allowed


@router.websocket("/api/ws/protocols/{protocol_id}")
async def protocol_collaboration(websocket: WebSocket, protocol_id: uuid.UUID) -> None:
    if not _origin_allowed(websocket):
        await websocket.close(code=4403)
        return
    token = websocket.cookies.get(settings.auth_session_cookie)
    user = await asyncio.to_thread(_authenticate, token)
    if user is None:
        await websocket.close(code=4401)
        return

    internal_protocol_id = await asyncio.to_thread(_load_and_authorize, protocol_id, user)
    if internal_protocol_id is None:
        await websocket.close(code=4403)
        return
    protocol_id = internal_protocol_id

    can_edit = _can_edit(user)

    await websocket.accept()
    redis = get_redis()
    collab = CollaborationService(redis)
    connection_id = uuid.uuid4().hex
    channel = collab.channel(protocol_id)

    pubsub = redis.pubsub()
    await pubsub.subscribe(channel)

    async def forward_from_redis() -> None:
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                if websocket.application_state != WebSocketState.CONNECTED:
                    break
                await websocket.send_text(message["data"])
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    forward_task = asyncio.create_task(forward_from_redis())

    # "A structured list this protocol references changed" notification, so a second
    # open protocol referencing the same list lights up its "Daten aktualisieren" hint
    # without needing a reload. This is a periodic DB poll rather than a Redis pub/sub
    # push: an earlier version pushed via a per-list Redis channel, but testing found
    # Redis pub/sub delivery to 2+ concurrent subscribers unreliable in this environment
    # (a message would silently fail to reach one of two subscribed connections in
    # roughly half of repeated trials, reproduced even across fully separate OS processes
    # and independent of connection-pool sharing - never root-caused further). A poll
    # every 15s is simple, has no such reliability question, and is a perfectly adequate
    # latency for a background "the data changed elsewhere" indicator.
    list_ids = await asyncio.to_thread(_referenced_list_ids, protocol_id)
    known_list_versions = await asyncio.to_thread(_list_content_versions, list_ids)
    public_list_ids = await asyncio.to_thread(_public_list_id_map, list_ids) if list_ids else {}

    async def poll_list_versions() -> None:
        try:
            while True:
                await asyncio.sleep(LIST_VERSION_POLL_INTERVAL_SECONDS)
                if websocket.application_state != WebSocketState.CONNECTED:
                    break
                current = await asyncio.to_thread(_list_content_versions, list_ids)
                for list_id, version in current.items():
                    if version > known_list_versions.get(list_id, 0):
                        known_list_versions[list_id] = version
                        await websocket.send_json({
                            "type": "list_changed",
                            "list_definition_id": str(public_list_ids[list_id]),
                            "content_version": version,
                        })
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    poll_task = asyncio.create_task(poll_list_versions()) if list_ids else None

    try:
        await collab.join(protocol_id, connection_id, user.user_id, user.display_name)
        presence = await collab.presence_snapshot(protocol_id)
        locks = await collab.locks_snapshot(protocol_id)
        # presence/locks entries carry OTHER users' internal ids too (not just `user`),
        # so translating them needs a batch DB lookup - the Redis-side presence/lock
        # storage itself stays internal-int throughout (see collaboration_service.py,
        # unchanged), only this outbound copy is rewritten to public ids.
        outbound_user_ids = {entry["user_id"] for entry in presence} | {entry["user_id"] for entry in locks.values()}
        public_user_ids = await asyncio.to_thread(_public_user_id_map, outbound_user_ids) if outbound_user_ids else {}
        public_presence = [{**entry, "user_id": str(public_user_ids[entry["user_id"]])} for entry in presence]
        public_locks = {key: {**entry, "user_id": str(public_user_ids[entry["user_id"]])} for key, entry in locks.items()}
        await websocket.send_json({
            "type": "snapshot",
            "presence": public_presence,
            "locks": public_locks,
            "self": {"user_id": str(user.user_public_id), "connection_id": connection_id, "can_edit": can_edit},
        })
        await collab.publish(protocol_id, {
            "type": "presence_join",
            "user_id": str(user.user_public_id),
            "display_name": user.display_name,
        })

        while True:
            raw = await websocket.receive_text()
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError):
                continue
            msg_type = payload.get("type")
            field_key = payload.get("field_key")

            if msg_type == "lock_request" and can_edit and field_key:
                holder = await collab.try_acquire_lock(protocol_id, field_key, connection_id, user.user_id, user.display_name)
                if holder is None:
                    await collab.publish(protocol_id, {
                        "type": "lock_acquired",
                        "field_key": field_key,
                        "user_id": str(user.user_public_id),
                        "display_name": user.display_name,
                    })
                else:
                    holder_public_id = await asyncio.to_thread(_public_user_id_map, {holder["user_id"]})
                    public_holder = {**holder, "user_id": str(holder_public_id[holder["user_id"]])}
                    await websocket.send_json({"type": "lock_denied", "field_key": field_key, "holder": public_holder})

            elif msg_type == "unlock" and field_key:
                released = await collab.release_lock(protocol_id, field_key, user.user_id, connection_id)
                if released:
                    await collab.publish(protocol_id, {"type": "lock_released", "field_key": field_key})

            elif msg_type == "heartbeat" and field_key:
                await collab.refresh_lock(protocol_id, field_key, user.user_id)

            elif msg_type == "field_update" and can_edit and field_key:
                # Only "block-*" keys participate in the lock system at all (see
                # focused-element-editor.tsx's lockField calls) - a few field_keys
                # (e.g. "element-titles", "track-changes-toggle") are pure "something
                # changed, go refetch" pings with no corresponding lock and stay
                # unguarded, same as before. For a "block-*" key, require the sender to
                # actually hold that lock (or, for matrix blocks, a cell lock nested
                # under it - see holds_lock_for_broadcast) before broadcasting: this is
                # the fix for the audit finding that field_update was broadcast
                # unconditionally, letting a client that never acquired (or lost) the
                # lock push a change that looked, to every other open tab, exactly like
                # a legitimate edit from the lock holder. Rejected updates are reported
                # only to the sender, not broadcast.
                if field_key.startswith("block-") and not await collab.holds_lock_for_broadcast(
                    protocol_id, field_key, user.user_id
                ):
                    await websocket.send_json({
                        "type": "field_update_rejected",
                        "field_key": field_key,
                        "reason": "lock_not_held",
                    })
                else:
                    await collab.publish(protocol_id, {
                        "type": "field_update",
                        "field_key": field_key,
                        "patch": payload.get("patch"),
                        "user_id": str(user.user_public_id),
                        "display_name": user.display_name,
                    })

            elif msg_type == "status_changed" and can_edit:
                await collab.publish(protocol_id, {
                    "type": "status_changed",
                    "status": payload.get("status"),
                    "user_id": str(user.user_public_id),
                    "display_name": user.display_name,
                })

    except WebSocketDisconnect:
        pass
    finally:
        forward_task.cancel()
        try:
            await forward_task
        except asyncio.CancelledError:
            pass
        if poll_task is not None:
            poll_task.cancel()
            try:
                await poll_task
            except asyncio.CancelledError:
                pass
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()

        released_fields = await collab.release_all_for_connection(protocol_id, connection_id)
        await collab.leave(protocol_id, connection_id)
        remaining_presence = await collab.presence_snapshot(protocol_id)
        still_present = any(int(entry.get("user_id", -1)) == user.user_id for entry in remaining_presence)

        for field_key in released_fields:
            await collab.publish(protocol_id, {"type": "lock_released", "field_key": field_key})
        if not still_present:
            await collab.publish(protocol_id, {
                "type": "presence_leave",
                "user_id": str(user.user_public_id),
                "display_name": user.display_name,
            })
