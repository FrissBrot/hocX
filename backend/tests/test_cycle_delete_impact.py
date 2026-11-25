"""Zyklus löschen (Fachentscheid 2026-11-25): die Kaskade bleibt, der Löschdialog nennt aber vorher,
was mitgeht - Tabellen-Verlauf, Zuordnungen von Aufgabenpaketen und Zyklus-Alben."""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.api.routes import cycle_configs as routes
from app.models.entities import PhotoAlbum, PhotoAlbumItem, TableSnapshot
from tests.factories import make_current_user, make_cycle_config, make_tenant


def test_delete_impact_counts_what_the_cascade_removes(db):
    tenant = make_tenant(db)
    cycle = make_cycle_config(db, tenant.id)
    other = make_cycle_config(db, tenant.id, name="Anderer")
    db.add(TableSnapshot(tenant_id=tenant.id, cycle_config_id=cycle.id, cycle_year=2026, table_name="Ämtli"))
    db.add(TableSnapshot(tenant_id=tenant.id, cycle_config_id=other.id, cycle_year=2026, table_name="Ämtli"))
    album = PhotoAlbum(tenant_id=tenant.id, name="Jahr 2026", kind="cycle", cycle_config_id=cycle.id, cycle_year=2026)
    db.add(album)
    db.flush()
    db.add_all([PhotoAlbumItem(album_id=album.id, file_id=uuid.uuid4()), PhotoAlbumItem(album_id=album.id, file_id=uuid.uuid4())])
    db.flush()
    admin = make_current_user(tenant.id, role="admin")

    impact = routes.cycle_config_delete_impact(cycle.public_id, db=db, user=admin)

    assert (impact.table_snapshot_count, impact.task_package_count, impact.album_count, impact.album_photo_count) == (1, 0, 1, 2)


def test_delete_impact_needs_templates_manage_and_the_own_tenant(db):
    tenant, foreign = make_tenant(db), make_tenant(db, "Fremd")
    cycle = make_cycle_config(db, tenant.id)
    with pytest.raises(HTTPException) as denied:
        routes.cycle_config_delete_impact(cycle.public_id, db=db, user=make_current_user(tenant.id, role="reader"))
    assert denied.value.status_code == 403
    with pytest.raises(HTTPException) as missing:
        routes.cycle_config_delete_impact(cycle.public_id, db=db, user=make_current_user(foreign.id, role="admin"))
    assert missing.value.status_code == 404
