"""Lokales S3 (Garage) im Systemstatus: eigener Check mit Bedarf und Belegung, und ein vom
Storage-Controller gestoppter Container gilt nicht als Ausfall."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.schemas.admin import ContainerStatusRead
from app.services import system_health_service

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


def _container(service: str, state: str) -> ContainerStatusRead:
    return system_health_service.evaluate_container(
        ContainerStatusRead(
            name=f"hocx-{service}-1", service=service, container_id="abc123def456", state=state,
            health=None, started_at=NOW - timedelta(hours=1), status="ok",
        )
    )


def _activate_local_s3(db, *, generation: int = 4242) -> None:
    profile_id = db.execute(
        text(
            "INSERT INTO storage_profile (name, provider, endpoint_url, bucket, is_builtin) "
            "VALUES ('Lokales S3 (Test)', 'garage_local', 'http://local-s3:3900', 'hocx-main', true) RETURNING id"
        )
    ).scalar_one()
    # Wie nach einer Migration: die bisherige Generation wartet in der Rückfallfrist.
    db.execute(text("UPDATE storage_generation SET status = 'retained' WHERE status = 'active'"))
    db.execute(
        text("INSERT INTO storage_generation (profile_id, generation, status) VALUES (:profile, :generation, 'active')"),
        {"profile": profile_id, "generation": generation},
    )
    db.execute(text("UPDATE storage_state SET active_profile_id = :profile, active_generation = :generation"), {"profile": profile_id, "generation": generation})
    db.execute(
        text(
            "INSERT INTO storage_object (namespace, key, size_bytes, generation) VALUES "
            "('main', 'a', 1073741824, :generation), ('main', 'b', 536870912, :generation)"
        ),
        {"generation": generation},
    )


def test_no_local_s3_check_without_a_local_profile(db):
    assert system_health_service._check_local_s3(db) == []


def test_local_s3_check_reports_need_and_usage_of_the_active_local_storage(db):
    _activate_local_s3(db)

    [check] = system_health_service._check_local_s3(db)

    assert check.key == "local_s3" and check.status == "ok"
    assert check.params == {"needed": 1, "reason": "active", "objects": 2, "gb": 1.5}


def test_stopped_local_s3_is_fine_when_it_is_not_needed(db):
    containers = [_container("local-s3", "exited"), _container("backend", "exited")]
    assert containers[0].status == "critical"

    marked = system_health_service.mark_intentionally_stopped_local_s3(db, containers)

    assert (marked[0].status, marked[0].reasons) == ("ok", ["not_needed"])
    # Andere gestoppte Dienste bleiben ein Ausfall.
    assert marked[1].status == "critical"


def test_stopped_local_s3_stays_critical_while_it_is_needed(db):
    _activate_local_s3(db)
    containers = [_container("local-s3", "exited")]

    marked = system_health_service.mark_intentionally_stopped_local_s3(db, containers)

    assert marked[0].status == "critical"
    assert "not_running" in marked[0].reasons
