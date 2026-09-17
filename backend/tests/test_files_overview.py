"""Tests for the "Dateien" overview page's backend: StoredFileRepository.list_tenant_files
(UNION ALL across protocol_image / word_import / submission_upload) and FileService.
list_tenant_files (content_url/ref_href derivation on top). Route-level require_writer
gating is tested by calling the route function directly as a plain callable, same
convention as tests/test_protocol_element_list_snapshot_routes.py.
"""
from datetime import date

import pytest
from fastapi import HTTPException

from app.api.routes import files as files_routes
from app.models.entities import PhotoAlbum, PhotoAlbumItem, StoredFile, SubmissionAssignment, SubmissionUpload, SubmissionUploadFile, WordImportDocument
from app.services.file_service import FileService
from tests.factories import (
    make_app_user,
    make_current_user,
    make_protocol,
    make_protocol_element,
    make_protocol_element_block,
    make_template,
    make_tenant,
)

service = FileService()


def _make_protocol_image(db, tenant_id, *, mime_type="image/png", scan_status="clean", created_by=None):
    template = make_template(db, tenant_id)
    protocol = make_protocol(db, tenant_id, template.id, protocol_number="7/2026", protocol_date=date(2026, 3, 4))
    element = make_protocol_element(db, protocol.id)
    block = make_protocol_element_block(db, element.id, configuration_snapshot_json={})
    stored_file = StoredFile(
        tenant_id=tenant_id, original_name="lager-foto.png", mime_type=mime_type,
        storage_path="uploads/tenant-x/block-x/lager-foto.png", scan_status=scan_status, created_by=created_by,
    )
    db.add(stored_file)
    db.flush()
    from app.models.entities import ProtocolImage
    image = ProtocolImage(protocol_element_block_id=block.id, stored_file_id=stored_file.id, sort_index=0)
    db.add(image)
    db.flush()
    return protocol, stored_file


def _make_word_import_document(db, tenant_id, *, display_name="1. Hock vom 14.10.2026.docx"):
    template = make_template(db, tenant_id)
    stored_file = StoredFile(
        tenant_id=tenant_id, original_name=display_name,
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        storage_path="uploads/word-imports/tenant-x/doc.docx",
    )
    db.add(stored_file)
    db.flush()
    document = WordImportDocument(
        tenant_id=tenant_id, template_id=template.id, stored_file_id=stored_file.id,
        original_filename=display_name, display_name=display_name, status="eingelesen",
    )
    db.add(document)
    db.flush()
    return document, stored_file


def _make_submission_upload_file(db, tenant_id, *, filename="beleg.pdf", delete_comment=None):
    assignment = SubmissionAssignment(
        tenant_id=tenant_id, title="Fotos Sommerlager", public_slug="fotos-sola",
        source_type="events", tag_filter="lager",
    )
    db.add(assignment)
    db.flush()
    upload = SubmissionUpload(assignment_id=assignment.id, event_id=None, list_entry_id=None, status="submitted")
    # SubmissionUpload requires exactly one of event_id/list_entry_id per its CHECK constraint;
    # tests here only exercise the file-listing join, not the assignment/upload domain logic,
    # so a minimal list-backed assignment is used to satisfy that constraint cheaply.
    from tests.factories import make_list_definition, make_list_entry
    list_definition = make_list_definition(db, tenant_id)
    entry = make_list_entry(db, list_definition.id)
    assignment.source_type = "list"
    assignment.list_definition_id = list_definition.id
    assignment.tag_filter = None
    upload.list_entry_id = entry.id
    db.add(upload)
    db.flush()
    stored_file = StoredFile(tenant_id=tenant_id, original_name=filename, mime_type="application/pdf", storage_path=f"abgabebox/{filename}")
    db.add(stored_file)
    db.flush()
    db.add(SubmissionUploadFile(upload_id=upload.id, stored_file_id=stored_file.id, delete_comment=delete_comment))
    db.flush()
    return assignment, upload, stored_file


def _make_gallery_image(db, tenant_id, *, mime_type="image/png", scan_status="clean", created_by=None, tags=None):
    from app.models.entities import GalleryImage

    stored_file = StoredFile(
        tenant_id=tenant_id, original_name="strand.png", mime_type=mime_type,
        storage_path="uploads/tenant-x/gallery/strand.png", scan_status=scan_status, created_by=created_by,
        tags=tags or [],
    )
    db.add(stored_file)
    db.flush()
    db.add(GalleryImage(tenant_id=tenant_id, stored_file_id=stored_file.id, created_by=created_by))
    db.flush()
    return stored_file


def test_list_tenant_files_includes_gallery_upload_with_expected_shape(db):
    tenant = make_tenant(db)
    stored_file = _make_gallery_image(db, tenant.id, tags=["Sommerlager"])

    items = service.list_tenant_files(db, tenant.id)

    assert len(items) == 1
    item = items[0]
    assert item.source == "gallery_upload"
    assert item.is_image is True
    assert item.ref_label == ""
    assert item.ref_href is None
    assert item.origin_tag == "Direkt hochgeladen"
    assert item.tags == ["Sommerlager"]
    assert item.content_url == f"/api/stored-files/{stored_file.public_id}/content"
    assert item.thumbnail_url == f"/api/stored-files/{stored_file.public_id}/thumbnail"


def test_list_tenant_files_includes_protocol_image_with_context(db):
    tenant = make_tenant(db)
    protocol, stored_file = _make_protocol_image(db, tenant.id)

    items = service.list_tenant_files(db, tenant.id)

    assert len(items) == 1
    item = items[0]
    assert item.source == "protocol_image"
    assert item.is_image is True
    assert item.ref_label == "7/2026"
    assert item.ref_href == f"/protocols/{protocol.public_id}"
    assert item.content_url == f"/api/stored-files/{stored_file.public_id}/content"


def test_list_tenant_files_includes_word_import_document(db):
    tenant = make_tenant(db)
    document, stored_file = _make_word_import_document(db, tenant.id)

    items = service.list_tenant_files(db, tenant.id)

    assert len(items) == 1
    item = items[0]
    assert item.source == "word_import"
    assert item.is_image is False
    assert item.ref_label == document.display_name
    assert item.ref_href is None
    assert item.content_url == f"/api/stored-files/{stored_file.public_id}/content"
    # .docx/.pdf are never images - no thumbnail to load, the grid shows a type icon instead.
    assert item.thumbnail_url is None


def test_list_tenant_files_sets_thumbnail_url_for_protocol_images(db):
    tenant = make_tenant(db)
    _, stored_file = _make_protocol_image(db, tenant.id)

    items = service.list_tenant_files(db, tenant.id)

    assert items[0].thumbnail_url == f"/api/stored-files/{stored_file.public_id}/thumbnail"


def test_list_tenant_files_sets_thumbnail_url_for_image_submission_uploads(db):
    tenant = make_tenant(db)
    _, upload, stored_file = _make_submission_upload_file(db, tenant.id, filename="foto.png")
    stored_file.mime_type = "image/png"
    db.flush()

    items = service.list_tenant_files(db, tenant.id)

    assert items[0].is_image is True
    assert items[0].thumbnail_url == f"/api/submission-uploads/{upload.public_id}/files/{stored_file.public_id}/thumbnail"


def test_list_tenant_files_includes_submission_upload_with_correct_content_url(db):
    tenant = make_tenant(db)
    assignment, upload, stored_file = _make_submission_upload_file(db, tenant.id)

    items = service.list_tenant_files(db, tenant.id)

    assert len(items) == 1
    item = items[0]
    assert item.source == "submission_upload"
    assert item.ref_label == "Fotos Sommerlager"
    assert item.ref_href == f"/submission-assignments/{assignment.id}"
    assert item.content_url == f"/api/submission-uploads/{upload.public_id}/files/{stored_file.public_id}/content"


def test_list_tenant_files_excludes_other_tenant_files(db):
    tenant_a = make_tenant(db, "Tenant A")
    tenant_b = make_tenant(db, "Tenant B")
    _make_protocol_image(db, tenant_a.id)
    _make_protocol_image(db, tenant_b.id)

    items = service.list_tenant_files(db, tenant_a.id)

    assert len(items) == 1


def test_list_tenant_files_only_images_filters_out_documents(db):
    tenant = make_tenant(db)
    _make_protocol_image(db, tenant.id)
    _make_word_import_document(db, tenant.id)

    all_items = service.list_tenant_files(db, tenant.id)
    image_items = service.list_tenant_files(db, tenant.id, only_images=True)

    assert len(all_items) == 2
    assert len(image_items) == 1
    assert image_items[0].is_image is True


def test_list_tenant_files_exclude_images_filters_out_photos(db):
    tenant = make_tenant(db)
    _make_protocol_image(db, tenant.id)
    _make_word_import_document(db, tenant.id)

    file_items = service.list_tenant_files(db, tenant.id, exclude_images=True)

    assert len(file_items) == 1
    assert file_items[0].is_image is False
    assert file_items[0].source == "word_import"


def test_list_tenant_files_source_filter(db):
    tenant = make_tenant(db)
    _make_protocol_image(db, tenant.id)
    _make_submission_upload_file(db, tenant.id)

    items = service.list_tenant_files(db, tenant.id, source="submission_upload")

    assert len(items) == 1
    assert items[0].source == "submission_upload"


def test_list_tenant_files_search_matches_original_name_case_insensitively(db):
    tenant = make_tenant(db)
    _make_word_import_document(db, tenant.id, display_name="Jahresbericht 2026.docx")

    hits = service.list_tenant_files(db, tenant.id, search="jahresbericht")
    misses = service.list_tenant_files(db, tenant.id, search="protokoll")

    assert len(hits) == 1
    assert len(misses) == 0


def test_list_tenant_files_excludes_infected_files(db):
    tenant = make_tenant(db)
    _make_protocol_image(db, tenant.id, scan_status="infected")

    items = service.list_tenant_files(db, tenant.id)

    assert items == []


def test_list_tenant_files_excludes_soft_deleted_submission_upload_files(db):
    tenant = make_tenant(db)
    _make_submission_upload_file(db, tenant.id, delete_comment="Falsche Datei hochgeladen")

    items = service.list_tenant_files(db, tenant.id)

    assert items == []


def test_list_files_route_requires_writer_role(db):
    tenant = make_tenant(db)
    reader = make_current_user(tenant.id, role="reader")

    with pytest.raises(HTTPException) as exc_info:
        files_routes.list_files(
            skip=0, limit=60, source=None, only_images=False, exclude_images=False, search=None, tags=None,
            sort_by="created_at", sort_dir="desc", db=db, user=reader,
        )
    assert exc_info.value.status_code == 403


def test_list_files_route_scopes_to_an_album_via_join_and_sorts_best_of_first(db):
    """Regression coverage (audit fix, 2026-09-17): album-scoped listing now joins
    photo_album_item by album_id in the DB query (StoredFileRepository.list_tenant_files'
    album_id param) instead of the route pre-fetching every member id into Python and
    passing it through file_ids' IN-list - covers both that the join correctly excludes
    non-members and that is_best still gets attached/sorted correctly, now fetched only
    for the returned page instead of the whole album."""
    tenant = make_tenant(db)
    writer = make_current_user(tenant.id, role="writer")
    in_album_not_best = _make_gallery_image(db, tenant.id)
    in_album_best = _make_gallery_image(db, tenant.id)
    not_in_album = _make_gallery_image(db, tenant.id)

    album = PhotoAlbum(tenant_id=tenant.id, name="Sommerlager", kind="manual")
    db.add(album)
    db.flush()
    db.add_all([
        PhotoAlbumItem(album_id=album.id, file_id=in_album_not_best.public_id, is_best=False),
        PhotoAlbumItem(album_id=album.id, file_id=in_album_best.public_id, is_best=True),
    ])
    db.commit()

    items = files_routes.list_files(
        skip=0, limit=60, source=None, only_images=False, exclude_images=False, search=None, tags=None,
        sort_by="created_at", sort_dir="desc", db=db, user=writer, album_id=album.id,
    )

    returned_ids = {item.id for item in items}
    assert returned_ids == {in_album_not_best.public_id, in_album_best.public_id}
    assert not_in_album.public_id not in returned_ids
    assert items[0].id == in_album_best.public_id
    assert items[0].is_best is True
    assert items[1].is_best is False


@pytest.mark.parametrize("album_filter", [{}, {"album_id": None}], ids=["omitted-album", "explicit-none"])
def test_list_files_route_returns_items_for_writer_role(db, album_filter):
    tenant = make_tenant(db)
    _make_protocol_image(db, tenant.id)
    writer = make_current_user(tenant.id, role="writer")

    result = files_routes.list_files(
        skip=0, limit=60, source=None, only_images=False, exclude_images=False, search=None, tags=None,
        sort_by="created_at", sort_dir="desc", db=db, user=writer, **album_filter,
    )

    assert len(result) == 1
    assert result[0].source == "protocol_image"


def test_list_tenant_files_defaults_tags_to_empty_and_sets_origin_tag_per_source(db):
    tenant = make_tenant(db)
    _make_protocol_image(db, tenant.id)
    _make_word_import_document(db, tenant.id)
    _make_submission_upload_file(db, tenant.id)

    items = {item.source: item for item in service.list_tenant_files(db, tenant.id)}

    assert all(item.tags == [] for item in items.values())
    assert items["protocol_image"].origin_tag == "Protokoll 7/2026 – Test Block"
    assert items["word_import"].origin_tag == "Word-Import: 1. Hock vom 14.10.2026.docx"
    assert items["submission_upload"].origin_tag == "Abgabe: Fotos Sommerlager"


def test_update_stored_file_tags_normalizes_trims_dedupes_and_drops_blanks(db):
    tenant = make_tenant(db)
    _, stored_file = _make_protocol_image(db, tenant.id)

    result = service.update_stored_file_tags(db, stored_file, ["  Lager  ", "Lager", "", "   ", "Foto"])

    assert result == ["Lager", "Foto"]
    items = service.list_tenant_files(db, tenant.id)
    assert items[0].tags == ["Lager", "Foto"]


def test_list_tenant_files_tags_filter_matches_custom_tag(db):
    tenant = make_tenant(db)
    _, stored_file_a = _make_protocol_image(db, tenant.id)
    _make_word_import_document(db, tenant.id)
    service.update_stored_file_tags(db, stored_file_a, ["Wichtig"])

    items = service.list_tenant_files(db, tenant.id, tags=["Wichtig"])

    assert len(items) == 1
    assert items[0].id == stored_file_a.public_id


def test_list_tenant_files_tags_filter_matches_origin_tag(db):
    tenant = make_tenant(db)
    _, stored_file_a = _make_protocol_image(db, tenant.id)
    _make_word_import_document(db, tenant.id)

    items = service.list_tenant_files(db, tenant.id, tags=["Protokoll 7/2026 – Test Block"])

    assert len(items) == 1
    assert items[0].id == stored_file_a.public_id


def test_list_tenant_files_tags_filter_requires_all_selected_tags(db):
    tenant = make_tenant(db)
    _, stored_file_a = _make_protocol_image(db, tenant.id)
    service.update_stored_file_tags(db, stored_file_a, ["Wichtig"])

    matches_both = service.list_tenant_files(db, tenant.id, tags=["Wichtig", "Protokoll 7/2026 – Test Block"])
    matches_missing = service.list_tenant_files(db, tenant.id, tags=["Wichtig", "Nicht vorhanden"])

    assert len(matches_both) == 1
    assert len(matches_missing) == 0


def test_list_distinct_tags_includes_custom_and_origin_tags_and_supports_substring_query(db):
    tenant = make_tenant(db)
    _, stored_file = _make_protocol_image(db, tenant.id)
    service.update_stored_file_tags(db, stored_file, ["Wichtig"])

    all_tags = service.list_distinct_tags(db, tenant.id)
    assert "Wichtig" in all_tags
    assert "Protokoll 7/2026 – Test Block" in all_tags

    filtered = service.list_distinct_tags(db, tenant.id, query="wich")
    assert filtered == ["Wichtig"]


def test_update_stored_file_tags_route_requires_writer_role(db):
    tenant = make_tenant(db)
    _, stored_file = _make_protocol_image(db, tenant.id)
    reader = make_current_user(tenant.id, role="reader")

    with pytest.raises(HTTPException) as exc_info:
        files_routes.update_stored_file_tags(
            stored_file.id, files_routes.StoredFileTagsUpdate(tags=["Wichtig"]), db=db, user=reader,
        )
    assert exc_info.value.status_code == 403


def test_update_stored_file_tags_route_persists_for_writer_role(db):
    tenant = make_tenant(db)
    _, stored_file = _make_protocol_image(db, tenant.id)
    writer = make_current_user(tenant.id, role="writer")

    result = files_routes.update_stored_file_tags(
        stored_file.public_id, files_routes.StoredFileTagsUpdate(tags=["Wichtig"]), db=db, user=writer,
    )

    assert result == ["Wichtig"]
    db.refresh(stored_file)
    assert stored_file.tags == ["Wichtig"]


def test_get_stored_file_metadata_includes_uploader_display_name(db):
    tenant = make_tenant(db)
    uploader = make_app_user(db, email="leiter@example.com", first_name="Anna", last_name="Muster")
    _, stored_file = _make_protocol_image(db, tenant.id, created_by=uploader.id)

    metadata = service.get_stored_file_metadata(db, stored_file, "/app/storage", tenant.id)

    assert metadata is not None
    assert metadata.uploaded_by_name == "Anna Muster"


def test_get_stored_file_metadata_uploaded_by_name_is_none_without_created_by(db):
    """Covers abgabebox submission uploads in particular: written by an anonymous public
    submitter through a restricted DB role that never sets created_by."""
    tenant = make_tenant(db)
    _, stored_file = _make_protocol_image(db, tenant.id, created_by=None)

    metadata = service.get_stored_file_metadata(db, stored_file, "/app/storage", tenant.id)

    assert metadata is not None
    assert metadata.uploaded_by_name is None


def test_list_tenant_files_protocol_image_group_date_and_context_label(db):
    tenant = make_tenant(db)
    protocol, _stored_file = _make_protocol_image(db, tenant.id)

    items = service.list_tenant_files(db, tenant.id)

    assert len(items) == 1
    assert items[0].group_date == protocol.protocol_date
    assert items[0].context_label == "Protokoll 7/2026 · Test Block"


def test_list_tenant_files_word_import_group_date_and_context_label(db):
    tenant = make_tenant(db)
    document, stored_file = _make_word_import_document(db, tenant.id, display_name="1. Hock vom 14.10.2026.docx")
    assert document.protocol_date is None  # not every imported doc has a recognized date

    items = service.list_tenant_files(db, tenant.id)

    assert len(items) == 1
    assert items[0].group_date == stored_file.created_at.date()
    assert items[0].context_label == document.display_name

    document.protocol_date = date(2026, 10, 14)
    db.commit()

    items = service.list_tenant_files(db, tenant.id)
    assert items[0].group_date == date(2026, 10, 14)


def test_list_tenant_files_submission_upload_group_date_and_context_label(db):
    tenant = make_tenant(db)
    assignment, _upload, stored_file = _make_submission_upload_file(db, tenant.id)

    items = service.list_tenant_files(db, tenant.id)

    assert len(items) == 1
    assert items[0].group_date == stored_file.created_at.date()
    assert items[0].context_label == assignment.title


def test_list_tenant_files_gallery_upload_without_event_falls_back_to_created_at_and_no_context(db):
    tenant = make_tenant(db)
    stored_file = _make_gallery_image(db, tenant.id)

    items = service.list_tenant_files(db, tenant.id)

    assert len(items) == 1
    assert items[0].group_date == stored_file.created_at.date()
    assert items[0].context_label is None


def test_list_tenant_files_gallery_upload_with_event_uses_event_date_and_title(db):
    """Regression for the outer join in _files_overview_branches' gallery branch: an
    event-less gallery upload must still list (covered above), and one *with* an event
    must pick up that event's date/title instead of falling back to created_at."""
    from app.models.entities import GalleryImage

    from tests.factories import make_event

    tenant = make_tenant(db)
    event = make_event(db, tenant.id, title="Sommerlager", event_date=date(2026, 7, 10))
    stored_file = StoredFile(
        tenant_id=tenant.id, original_name="lager.png", mime_type="image/png",
        storage_path="uploads/tenant-x/gallery/lager.png", scan_status="clean",
    )
    db.add(stored_file)
    db.flush()
    db.add(GalleryImage(tenant_id=tenant.id, stored_file_id=stored_file.id, event_id=event.id))
    db.flush()

    items = service.list_tenant_files(db, tenant.id)

    assert len(items) == 1
    assert items[0].group_date == event.event_date
    assert items[0].context_label == "Sommerlager"


def test_list_tenant_files_face_analyzed_at_reflects_the_column(db):
    tenant = make_tenant(db)
    stored_file = _make_gallery_image(db, tenant.id)

    items = service.list_tenant_files(db, tenant.id)
    assert items[0].face_analyzed_at is None

    from datetime import datetime, timezone

    stored_file.face_analyzed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    db.commit()

    items = service.list_tenant_files(db, tenant.id)
    assert items[0].face_analyzed_at == stored_file.face_analyzed_at


def test_attach_album_context_fills_albums_and_unscoped_is_best(db):
    from app.models.entities import PhotoAlbum, PhotoAlbumItem
    from app.services import photo_album_service

    tenant = make_tenant(db)
    stored_file = _make_gallery_image(db, tenant.id)
    other_stored_file = _make_gallery_image(db, tenant.id)
    other_stored_file.original_name = "andere.png"
    album = PhotoAlbum(tenant_id=tenant.id, name="Ferien", kind="manual")
    db.add(album)
    db.flush()
    photo_album_service.add_items(db, album, [stored_file.public_id])
    db.execute(
        PhotoAlbumItem.__table__.update()
        .where(PhotoAlbumItem.album_id == album.id, PhotoAlbumItem.file_id == stored_file.public_id)
        .values(is_best=True)
    )
    db.commit()

    items = service.list_tenant_files(db, tenant.id)
    service.attach_album_context(db, tenant.id, items)

    by_id = {item.id: item for item in items}
    in_album = by_id[stored_file.public_id]
    assert len(in_album.albums) == 1
    assert in_album.albums[0].name == "Ferien"
    assert in_album.albums[0].is_best is True
    assert in_album.is_best is True

    not_in_album = by_id[other_stored_file.public_id]
    assert not_in_album.albums == []
    assert not_in_album.is_best is None
