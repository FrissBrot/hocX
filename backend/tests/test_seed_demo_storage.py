"""Demo-Seed (scripts/seed_test_tenant.py): Abgabe-Dateien überleben den nächsten Seed-Lauf.

Jeder Test-Deploy löscht den Demo-Mandanten und baut ihn neu auf. Das Löschen hinterlässt
Tombstones, die der Purge-Job kurz darauf physisch entfernt. Früher schrieb der Seed die Dateien
unter festen Schlüsseln direkt auf die Platte, und der Purge löschte die frisch geschriebenen
Dateien gleich wieder.
"""

from __future__ import annotations

from sqlalchemy import select

from app.core.config import settings
from app.core.storage import ABGABEBOX, get_object_store
from app.models import StorageObject
from scripts.seed_test_tenant import store_demo_submission_file


def test_demo_submission_file_survives_purge_of_previous_seed(db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "abgabebox_storage_root", str(tmp_path / "abgabebox"))
    store = get_object_store()

    # Vorheriger Lauf: Datei des alten Demo-Mandanten, danach Mandant gelöscht (Tombstone).
    old_key = store_demo_submission_file(db, 101, "foto.jpg", b"alt", "image/jpeg")
    store.delete(db, ABGABEBOX, old_key)

    new_key = store_demo_submission_file(db, 102, "foto.jpg", b"neu", "image/jpeg")
    store.purge_deleted(db)

    assert new_key != old_key
    assert (tmp_path / "abgabebox" / new_key).read_bytes() == b"neu"
    assert not (tmp_path / "abgabebox" / old_key).exists()
    row = db.scalars(select(StorageObject).where(StorageObject.namespace == ABGABEBOX, StorageObject.key == new_key)).one()
    assert row.status == "active"
    assert row.purge_pending is False
