"""Ein Upload über die Fenster «Fotos»/«Dateien» mit einem Abgabe-Element als Bezug schreibt in
die Abgabe (zählt für max_files, Abgabe-Übersicht, Pendenzen). Das darf nur, wer Abgaben
verwalten darf (submissions.manage) und dessen Mandant die Abgabebox voll gebucht hat - ein
Konto mit nur files.manage bzw. ein Mandant im Nur-Lesen-Zustand nach einem Downgrade nicht."""
import dataclasses

import pytest
from fastapi import HTTPException

from app.models.entities import GalleryImage, StoredFile
from tests.factories import make_current_user, make_tenant, system_role_permissions
from tests.test_submission_upload_rules import (  # noqa: F401 - Fixture wird per autouse genutzt
    PDF,
    _isolated_storage_root,
    _make_assignment,
    _upload_documents,
    _upload_file,
)


def _assert_nothing_stored(db, tenant_id):
    assert db.query(StoredFile).filter_by(tenant_id=tenant_id).count() == 0
    assert db.query(GalleryImage).filter_by(tenant_id=tenant_id).count() == 0


def test_files_manage_without_submissions_manage_cannot_upload_into_an_abgabe(db):
    tenant = make_tenant(db)
    photographer = make_current_user(tenant.id, permissions=frozenset({"meetings.read", "files.manage"}))
    assignment, ref, _ = _make_assignment(db, tenant.id)

    with pytest.raises(HTTPException) as exc_info:
        _upload_documents(db, photographer, assignment, ref, [_upload_file(PDF, "a.pdf")])

    assert exc_info.value.status_code == 403
    _assert_nothing_stored(db, tenant.id)


def test_upload_into_an_abgabe_is_blocked_when_abgabebox_is_only_read_only(db):
    tenant = make_tenant(db)
    writer = make_current_user(tenant.id, role="writer")
    writer = dataclasses.replace(
        writer,
        current_tenant_features=writer.current_tenant_features - {"abgabebox"},
        current_tenant_read_only_features=frozenset({"abgabebox"}),
    )
    assignment, ref, _ = _make_assignment(db, tenant.id)

    with pytest.raises(HTTPException) as exc_info:
        _upload_documents(db, writer, assignment, ref, [_upload_file(PDF, "a.pdf")])

    assert exc_info.value.status_code == 403
    _assert_nothing_stored(db, tenant.id)


def test_writer_with_submissions_manage_can_still_upload_into_an_abgabe(db):
    tenant = make_tenant(db)
    writer = make_current_user(tenant.id, permissions=system_role_permissions("writer"))
    assignment, ref, _ = _make_assignment(db, tenant.id)

    result = _upload_documents(db, writer, assignment, ref, [_upload_file(PDF, "a.pdf")])

    assert result.errors == []
    assert db.query(GalleryImage).filter_by(tenant_id=tenant.id).one().submission_assignment_id == assignment.id
