"""Tags für die Pendenzen einer Abgabe (Migration 0202).

In der Abgabe gewählte Tags bekommt jede Pendenz; «Abgabe-Tag erstellen» (todo_own_tag, Standard
aus) gibt zusätzlich ein Tag mit dem Titel der Abgabe. Eine Änderung der Abgabe nimmt nur die
vorher vorgegebenen Tags weg, von Hand gesetzte Tags bleiben.
"""
from __future__ import annotations

from sqlalchemy import select

from app.api.routes import submission_assignments as routes
from app.models import ProtocolTodo
from app.schemas.submission import SubmissionAssignmentCreate, SubmissionAssignmentUpdate, clean_todo_tags
from app.services.submission_service import merge_submission_todo_tags
from tests.test_submission_manual_elements import _create, org  # noqa: F401 - Fixture


def _todo_tags(db, assignment) -> list[str]:
    todos = db.scalars(select(ProtocolTodo).where(ProtocolTodo.submission_assignment_id == assignment.id)).all()
    assert len(todos) == 1
    db.refresh(todos[0])
    return list(todos[0].tags)


def _element(org):
    return [{"name": "Bericht", "responsible_participant_ids": [org["anna"].public_id]}]


def test_clean_todo_tags_trims_and_dedupes():
    assert clean_todo_tags([" Lager ", "lager", "", "Hock", "x" * 100]) == ["Lager", "Hock", "x" * 80]


def test_merge_keeps_manual_tags_and_replaces_managed_ones():
    assert merge_submission_todo_tags(["Alt", "Eigenes"], previous=["Alt"], wanted=["Neu"]) == ["Eigenes", "Neu"]
    assert merge_submission_todo_tags(["neu"], previous=[], wanted=["Neu"]) == ["neu"]


def test_default_is_no_tags_and_no_own_tag(db, org):
    read, assignment = _create(db, org, _element(org))
    assert read.todo_tags == [] and read.todo_own_tag is False
    assert _todo_tags(db, assignment) == []


def test_configured_and_own_tag_reach_every_todo(db, org):
    read, assignment = _create(db, org, _element(org), title="Sommerlager", public_slug="sommerlager", todo_tags=["Lager", "Eltern"], todo_own_tag=True)
    assert read.todo_tags == ["Lager", "Eltern"] and read.todo_own_tag is True
    assert _todo_tags(db, assignment) == ["Lager", "Eltern", "Sommerlager"]


def test_change_removes_only_previously_managed_tags(db, org):
    read, assignment = _create(db, org, _element(org), title="Sommerlager", public_slug="sommerlager", todo_tags=["Lager"], todo_own_tag=True)
    todo = db.scalar(select(ProtocolTodo).where(ProtocolTodo.submission_assignment_id == assignment.id))
    todo.tags = [*todo.tags, "Von Hand"]
    db.commit()

    # Tag gewechselt, Titel geändert, eigenes Tag bleibt an
    routes.patch_assignment(read.id, SubmissionAssignmentUpdate(title="Herbstlager", todo_tags=["Material"]), db=db, user=org["user"])
    assert _todo_tags(db, assignment) == ["Von Hand", "Material", "Herbstlager"]

    # Eigenes Tag aus: nur dieses fällt weg
    routes.patch_assignment(read.id, SubmissionAssignmentUpdate(todo_own_tag=False), db=db, user=org["user"])
    assert _todo_tags(db, assignment) == ["Von Hand", "Material"]

    # null = unverändert
    routes.patch_assignment(read.id, SubmissionAssignmentUpdate(todo_tags=None, todo_own_tag=None), db=db, user=org["user"])
    assert _todo_tags(db, assignment) == ["Von Hand", "Material"]


def test_too_many_tags_are_rejected():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SubmissionAssignmentCreate(title="x", public_slug="x", source_type="manual", todo_tags=[f"t{i}" for i in range(21)])
