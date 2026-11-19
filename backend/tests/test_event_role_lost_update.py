"""Nachtlauf 2026-11-19 (Verdacht «Lost Update der Rollen-Arrays»): Rollenfelder eines Termins
(participant_ids, organizer_ids, ...) kamen vom Client immer als ganze Liste. Fügten zwei Personen
gleichzeitig je jemanden hinzu, überschrieb die zweite Speicherung die erste.

Jetzt schickt der Client mit ``role_ids_base`` den Stand, von dem er ausging. Der Server übernimmt
unter der Zeilensperre nur die Differenz (hinzugefügt/entfernt) auf den aktuellen Stand. Ohne
``role_ids_base`` (ältere Clients, CSV, Word-Import) gilt die Liste wie bisher als Ersatz."""

from app.models import Event
from app.schemas.event import EventUpdate
from app.services.event_service import EventService
from tests.factories import make_event, make_participant, make_tenant


def _setup(db):
    tenant = make_tenant(db)
    event = make_event(db, tenant.id)
    people = [make_participant(db, tenant.id, name) for name in ("Anna", "Bruno", "Carla", "Dario")]
    return tenant, event, people


def _ids(db, event_id, field="participant_ids"):
    db.expire_all()
    return getattr(db.get(Event, event_id), field) or []


def test_two_additions_from_the_same_base_are_both_kept(db):
    _tenant, event, (anna, bruno, carla, _dario) = _setup(db)
    service = EventService()
    service.update_event(db, event.id, EventUpdate(participant_ids=[anna.public_id]))

    # Beide Personen sahen nur Anna; die eine fügt Bruno hinzu, die andere Carla.
    service.update_event(db, event.id, EventUpdate.model_validate({
        "participant_ids": [anna.public_id, bruno.public_id], "role_ids_base": {"participant_ids": [anna.public_id]},
    }))
    service.update_event(db, event.id, EventUpdate.model_validate({
        "participant_ids": [anna.public_id, carla.public_id], "role_ids_base": {"participant_ids": [anna.public_id]},
    }))

    assert _ids(db, event.id) == [anna.id, bruno.id, carla.id]


def test_removal_from_a_stale_base_keeps_concurrent_addition(db):
    _tenant, event, (anna, bruno, carla, _dario) = _setup(db)
    service = EventService()
    service.update_event(db, event.id, EventUpdate(organizer_ids=[anna.public_id, bruno.public_id]))
    # Jemand anderes hat inzwischen Carla hinzugefügt.
    service.update_event(db, event.id, EventUpdate.model_validate({
        "organizer_ids": [anna.public_id, bruno.public_id, carla.public_id],
        "role_ids_base": {"organizer_ids": [anna.public_id, bruno.public_id]},
    }))

    # Veralteter Client entfernt Anna (er kennt Carla noch nicht).
    service.update_event(db, event.id, EventUpdate.model_validate({
        "organizer_ids": [bruno.public_id], "role_ids_base": {"organizer_ids": [anna.public_id, bruno.public_id]},
    }))

    assert _ids(db, event.id, "organizer_ids") == [bruno.id, carla.id]


def test_base_with_unknown_ids_is_tolerated(db):
    """Eine inzwischen gelöschte Person im Ausgangsstand bricht das Speichern nicht."""
    import uuid

    _tenant, event, (anna, bruno, _carla, _dario) = _setup(db)
    service = EventService()
    service.update_event(db, event.id, EventUpdate(leadership_ids=[anna.public_id]))

    service.update_event(db, event.id, EventUpdate.model_validate({
        "leadership_ids": [anna.public_id, bruno.public_id],
        "role_ids_base": {"leadership_ids": [anna.public_id, uuid.uuid4()]},
    }))

    assert _ids(db, event.id, "leadership_ids") == [anna.id, bruno.id]


def test_without_base_the_list_replaces_as_before(db):
    _tenant, event, (anna, bruno, carla, _dario) = _setup(db)
    service = EventService()
    service.update_event(db, event.id, EventUpdate(participant_ids=[anna.public_id, bruno.public_id]))

    service.update_event(db, event.id, EventUpdate(participant_ids=[carla.public_id]))

    assert _ids(db, event.id) == [carla.id]
