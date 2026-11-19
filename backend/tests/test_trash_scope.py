"""Papierkorb-Hook (app/core/trash_scope.py): eine Datei mit deleted_at ist für jede ORM-Abfrage
unsichtbar - als Entität, als Spalte, als Aggregat, in Joins/Aliassen/Unterabfragen und über
Session.get - solange der Papierkorb nicht ausdrücklich eingeblendet wird."""

from datetime import UTC, datetime

from sqlalchemy import func, literal, select, union_all
from sqlalchemy.orm import aliased

from app.core.trash_scope import INCLUDE_TRASHED, include_trashed
from app.models import GalleryImage, StoredFile
from tests.factories import make_tenant


def _file(db, tenant_id: int, name: str, *, trashed: bool) -> StoredFile:
    stored_file = StoredFile(
        tenant_id=tenant_id,
        original_name=name,
        mime_type="image/png",
        storage_path=f"uploads/trash-scope/{name}",
        file_size_bytes=10,
        scan_status="clean",
        deleted_at=datetime.now(UTC) if trashed else None,
    )
    db.add(stored_file)
    db.flush()
    db.add(GalleryImage(tenant_id=tenant_id, stored_file_id=stored_file.id))
    db.flush()
    return stored_file


def _setup(db):
    tenant = make_tenant(db)
    visible = _file(db, tenant.id, "sichtbar.png", trashed=False)
    trashed = _file(db, tenant.id, "papierkorb.png", trashed=True)
    ids = (visible.id, trashed.id)
    tenant_id = tenant.id
    db.commit()
    db.expunge_all()  # Identity-Map leeren: Session.get soll wirklich abfragen
    return tenant_id, ids


def test_entities_columns_and_aggregates_hide_trashed(db):
    tenant_id, (visible_id, trashed_id) = _setup(db)
    assert db.scalars(select(StoredFile.id).where(StoredFile.tenant_id == tenant_id)).all() == [visible_id]
    assert [f.id for f in db.scalars(select(StoredFile).where(StoredFile.tenant_id == tenant_id))] == [visible_id]
    assert db.scalar(select(func.sum(StoredFile.file_size_bytes)).where(StoredFile.tenant_id == tenant_id)) == 10
    assert db.scalar(select(func.count()).select_from(StoredFile).where(StoredFile.tenant_id == tenant_id)) == 1
    assert db.get(StoredFile, trashed_id) is None
    assert db.get(StoredFile, visible_id) is not None


def test_joins_aliases_and_subqueries_hide_trashed(db):
    tenant_id, (visible_id, trashed_id) = _setup(db)
    joined = db.scalars(
        select(GalleryImage.stored_file_id)
        .join(StoredFile, StoredFile.id == GalleryImage.stored_file_id)
        .where(GalleryImage.tenant_id == tenant_id)
    ).all()
    assert joined == [visible_id]
    alias = aliased(StoredFile)
    outer = db.execute(
        select(GalleryImage.stored_file_id, alias.id)
        .outerjoin(alias, alias.id == GalleryImage.stored_file_id)
        .where(GalleryImage.tenant_id == tenant_id)
        .order_by(GalleryImage.stored_file_id)
    ).all()
    assert sorted(outer, key=lambda row: row[0]) == sorted([(visible_id, visible_id), (trashed_id, None)], key=lambda row: row[0])
    sub = db.scalars(
        select(GalleryImage.stored_file_id).where(
            GalleryImage.tenant_id == tenant_id, GalleryImage.stored_file_id.in_(select(StoredFile.id))
        )
    ).all()
    assert sub == [visible_id]
    union = union_all(
        select(StoredFile.id, literal("a")).where(StoredFile.tenant_id == tenant_id),
        select(StoredFile.id, literal("b")).where(StoredFile.tenant_id == tenant_id),
    ).subquery()
    assert sorted(db.scalars(select(union.c.id)).all()) == [visible_id, visible_id]


def test_opt_in_shows_trash(db):
    tenant_id, (visible_id, trashed_id) = _setup(db)
    with include_trashed(db):
        assert sorted(db.scalars(select(StoredFile.id).where(StoredFile.tenant_id == tenant_id))) == sorted([visible_id, trashed_id])
        with include_trashed(db):
            assert db.get(StoredFile, trashed_id) is not None
        # verschachtelt: der äussere Block bleibt offen
        assert db.scalar(select(func.count()).select_from(StoredFile).where(StoredFile.tenant_id == tenant_id)) == 2
    db.expunge_all()
    assert db.get(StoredFile, trashed_id) is None
    option = select(StoredFile.id).where(StoredFile.tenant_id == tenant_id).execution_options(**{INCLUDE_TRASHED: True})
    assert len(db.scalars(option).all()) == 2


def test_loaded_object_stays_usable_after_trashing(db):
    """Attribut-Refresh nach Commit (is_column_load) bleibt ungefiltert."""
    tenant_id, (visible_id, _trashed_id) = _setup(db)
    stored_file = db.get(StoredFile, visible_id)
    stored_file.deleted_at = datetime.now(UTC)
    db.commit()
    assert stored_file.original_name == "sichtbar.png"
