"""Nebenläufigkeit: Document-Studio-Asset löschen, während ein Brand-Profil es neu verwendet.

Ein verwendetes Asset darf nicht gelöscht werden (``asset_references``: veröffentlichte Stände und
Exporte müssen reproduzierbar bleiben). Brand-Profile verweisen aber nur im JSON auf ein Asset,
ohne Fremdschlüssel. ``update_brand`` prüfte das Asset (``_check_asset_refs``), ``delete_asset``
die Verwendungen - beide ohne Sperre des Assets. Speichert jemand das Logo ins Profil, während ein
anderer (z. B. «Duplikate zusammenführen» oder Löschen in der Asset-Liste) es entfernt, sieht die
Löschung die noch nicht festgeschriebene Revision nicht: Danach zeigt das aktuelle Profil auf ein
gelöschtes Asset, die Datei wird vom Speicherjob entfernt. Erwartet: Das Löschen wartet und lehnt
mit «Asset in Verwendung» ab.

Wie ``test_document_studio_race.py`` ohne ``db``-Fixture (echte, festgeschriebene Transaktionen).
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import engine
from app.core.storage import MAIN, get_object_store
from app.documents import assets as asset_service
from app.documents import brand_service
from app.documents.brand import BrandTokens
from app.models import DocumentAsset, DocumentBrand
from tests.factories import make_tenant


def _session() -> Session:
    return Session(bind=engine.connect(), autoflush=False, future=True)


def _close(session: Session) -> None:
    connection = session.connection()
    session.close()
    connection.close()


@pytest.fixture
def tenant_id():
    session = _session()
    try:
        tenant = make_tenant(session, "Asset löschen parallel")
        session.commit()
        tid = tenant.id
    finally:
        _close(session)
    yield tid
    with engine.connect() as connection:
        connection.execute(text("DELETE FROM tenant WHERE id = :tid"), {"tid": tid})
        connection.commit()


def _wait_until_blocked(timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    with engine.connect() as probe:
        while time.monotonic() < deadline:
            waiting = probe.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock' AND datname = current_database()"))
            # pg_stat_activity ist je Transaktion ein fester Schnappschuss: jede Abfrage neu
            probe.rollback()
            if waiting:
                return True
            time.sleep(0.05)
    return False


def test_delete_waits_for_brand_using_the_asset(tenant_id):
    setup = _session()
    try:
        key = f"document_assets/tenant-{tenant_id}/race-logo.png"
        get_object_store().put_bytes(setup, MAIN, key, b"logo")
        asset = DocumentAsset(tenant_id=tenant_id, kind="image", category="logo", name="Logo", storage_path=key, mime_type="image/png")
        setup.add(asset)
        setup.flush()
        brand = brand_service.create_brand(setup, tenant_id, name="Vereinsstil")
        setup.commit()
        asset_id, asset_public_id, brand_id = asset.id, asset.public_id, brand.id
    finally:
        _close(setup)

    def delete_in_other_request() -> None:
        session = _session()
        try:
            asset_service.delete_asset(session, session.get(DocumentAsset, asset_id))
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            _close(session)

    editor = _session()
    try:
        # Logo ins Profil übernommen, Commit steht noch aus
        brand_service.update_brand(
            editor, editor.get(DocumentBrand, brand_id), expected_lock_version=None,
            tokens=BrandTokens.model_validate({"assets": {"logo": str(asset_public_id)}}),
        )
        with ThreadPoolExecutor(1) as pool:
            deletion = pool.submit(delete_in_other_request)
            _wait_until_blocked(3.0)  # ohne Sperre läuft das Löschen sofort durch
            editor.commit()
            with pytest.raises(asset_service.AssetValidationError):
                deletion.result(timeout=15)
    finally:
        _close(editor)

    with Session(engine) as check:
        assert check.get(DocumentAsset, asset_id) is not None
        brand = check.get(DocumentBrand, brand_id)
        assert brand_service.tokens_of(brand_service.current_revision(check, brand)).assets.logo == asset_public_id


def test_merge_duplicates_keeps_used_copy_and_removes_unused(tenant_id):
    session = _session()
    try:
        ids = []
        for name in ("Logo", "Logo Kopie", "Logo Kopie 2"):
            key = f"document_assets/tenant-{tenant_id}/{len(ids)}.png"
            get_object_store().put_bytes(session, MAIN, key, b"logo")
            asset = DocumentAsset(tenant_id=tenant_id, kind="image", category="logo", name=name, storage_path=key, mime_type="image/png", checksum_sha256="a" * 64)
            session.add(asset)
            session.flush()
            ids.append((asset.id, asset.public_id))
        # Die jüngste Kopie ist verwendet und bleibt, die beiden anderen fallen weg
        brand_service.create_brand(session, tenant_id, name="Stil", tokens=BrandTokens.model_validate({"assets": {"logo": str(ids[2][1])}}))
        session.commit()
        assert asset_service.merge_duplicates(session, tenant_id) == 2
        session.commit()
        remaining = [asset.id for asset in asset_service.list_assets(session, tenant_id)]
        assert remaining == [ids[2][0]]
    finally:
        _close(session)
