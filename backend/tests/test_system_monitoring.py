"""Tests für das Systemmonitoring: Auswertung der Docker-Daten (system_health_service), Ableitung
und Benachrichtigung von Problemen (system_alert_service), ntfy-Einstellungen und die Endpunkte
/api/admin/system-status, /api/admin/notifications* und /api/system-status/summary."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text

from app.api.routes import admin as admin_routes
from app.api.routes import system_status as system_status_routes
from app.core.admin_security import CurrentAdmin
from app.models import PlatformNotificationSettings, SystemAlertState, SystemHealthEvent
from app.schemas.admin import ContainerStatusRead, HealthCheckRead, JobStatusOverview, NotificationSettingsWrite, SystemHealthSnapshot
from app.services import ntfy_client, system_alert_service, system_health_service
from app.services.notification_settings_service import NotificationSettingsService

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)


class _FakeRequest:
    def __init__(self, headers: dict[str, str] | None = None) -> None:
        self.headers = headers or {}


def _admin() -> CurrentAdmin:
    return CurrentAdmin(admin_id=1, admin_public_id=uuid.uuid4(), email="admin@example.com", display_name="Test Admin", role="owner")


def _container(service: str = "backend", **overrides) -> ContainerStatusRead:
    values = dict(
        name=f"hocx-{service}-1", service=service, container_id="abc123def456", state="running", health="healthy",
        started_at=NOW - timedelta(hours=1), status="ok",
    )
    values.update(overrides)
    return system_health_service.evaluate_container(ContainerStatusRead(**values))


def _snapshot(*, containers=None, checks=None, collected_at=NOW) -> SystemHealthSnapshot:
    return SystemHealthSnapshot(
        collected_at=collected_at, docker_configured=True, docker_available=True,
        containers=containers or [_container()], checks=checks or [HealthCheckRead(key="postgres", status="ok")],
    )


@pytest.fixture
def clean_state(db, monkeypatch):
    # Die Test-DB teilen sich alle Tests; echte Loops (lifespan smoke) schreiben dort Job-Zeilen.
    db.execute(text("DELETE FROM system_job_status"))
    db.execute(text("DELETE FROM system_alert_state"))
    db.execute(text("DELETE FROM system_health_event"))
    db.execute(text("DELETE FROM platform_notification_settings"))
    # Registrierte Loops ohne Lauf gelten erst 30 min nach Prozessstart als Problem.
    monkeypatch.setattr(system_alert_service, "_PROCESS_STARTED_AT", NOW)
    return db


@pytest.fixture
def no_jobs(monkeypatch):
    """Alarm-Tests ohne Job-Probleme: mit geleerter Job-Tabelle gälten sonst alle registrierten
    Loops als "nie gelaufen" und würden Zählungen verfälschen."""

    class _NoJobs:
        def get_overview(self, db, *, now=None):
            return JobStatusOverview(items=[], generated_at=now or NOW)

    monkeypatch.setattr(system_alert_service, "AdminJobStatusService", _NoJobs)


@pytest.fixture
def sent(monkeypatch, no_jobs):
    messages: list[ntfy_client.NtfyMessage] = []
    monkeypatch.setattr(ntfy_client, "send", lambda *, server_url, topic, token, message: messages.append(message))
    return messages


def _enable_ntfy(db) -> None:
    NotificationSettingsService().update(db, NotificationSettingsWrite(
        ntfy_enabled=True, ntfy_server_url="https://ntfy.example", ntfy_topic="hocx-alerts", admin_url="https://admin.example",
    ))


# ── system_health_service ────────────────────────────────────────────────────────────────


def test_evaluate_container_flags_unhealthy_stopped_oom_and_memory():
    assert _container().status == "ok"
    assert _container(health="unhealthy").reasons == ["unhealthy"]
    stopped = _container(state="exited", health=None, exit_code=137, oom_killed=True)
    assert stopped.status == "critical" and stopped.reasons == ["not_running", "oom_killed"]
    memory = _container(memory_bytes=950, memory_limit_bytes=1000)
    assert (memory.status, memory.reasons) == ("warning", ["memory_high"])


@pytest.mark.parametrize(
    ("image", "tag"),
    [
        ("ghcr.io/acme/hocx-backend:1.2.0", "1.2.0"),
        ("redis:7-alpine", "7-alpine"),
        ("clamav/clamav@sha256:9cb27d7660bd", None),
        ("localhost:5000/hocx-backend", None),
        (None, None),
    ],
)
def test_image_tag(image, tag):
    assert system_health_service.image_tag(image) == tag


def test_parse_clamav_version():
    version, signatures = system_health_service.parse_clamav_version("ClamAV 1.4.3/27790/Sat Oct 11 08:23:03 2026")
    assert version == "27790"
    assert signatures == datetime(2026, 10, 11, 8, 23, 3, tzinfo=timezone.utc)
    assert system_health_service.parse_clamav_version("ClamAV 1.4.3") == (None, None)


def test_cpu_percent_from_docker_stats():
    stats = {
        "cpu_stats": {"cpu_usage": {"total_usage": 2_000_000}, "system_cpu_usage": 20_000_000, "online_cpus": 4},
        "precpu_stats": {"cpu_usage": {"total_usage": 1_000_000}, "system_cpu_usage": 10_000_000},
    }
    assert system_health_service._cpu_percent(stats) == 40.0
    assert system_health_service._cpu_percent({"cpu_stats": {}, "precpu_stats": {}}) is None


def test_detect_container_restarts_ignores_recreated_containers(clean_state):
    db = clean_state
    previous = _snapshot(containers=[_container("backend"), _container("frontend", container_id="old000000000")])
    current = _snapshot(containers=[
        _container("backend", started_at=NOW, restart_count=1),  # gleiche ID, neuer Start -> Neustart
        _container("frontend", container_id="new000000000", started_at=NOW),  # neue ID -> Deploy
    ])

    system_health_service.detect_container_restarts(db, previous, current)

    events = db.scalars(select(SystemHealthEvent)).all()
    assert [(event.kind, event.subject) for event in events] == [("container_restart", "container:backend")]


def test_collect_checks_turns_unreachable_services_into_findings(clean_state, monkeypatch):
    monkeypatch.setattr(system_health_service, "_check_redis", lambda: (_ for _ in ()).throw(ConnectionError("refused")))
    monkeypatch.setattr(system_health_service, "_check_clamav", lambda now: (_ for _ in ()).throw(ConnectionError("no clamd")))

    checks = {check.key: check for check in system_health_service.collect_checks(clean_state, NOW)}

    assert checks["postgres"].status == "ok"
    assert (checks["redis"].status, checks["redis"].error) == ("critical", "ConnectionError: refused")
    assert checks["clamav"].status == "critical"
    # Ohne Verbindung ist das Signaturalter unbekannt - kein zweiter Alarm.
    assert checks["clamav_signatures"].status == "unknown"


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_document_verification_check_expects_a_miss_for_the_probe_hash(monkeypatch):
    sent = {}

    def fake_urlopen(request, timeout):
        sent.update(url=request.full_url, body=json.loads(request.data), timeout=timeout)
        return _FakeResponse(b'{"found": false}')

    monkeypatch.setattr(system_health_service.urllib.request, "urlopen", fake_urlopen)
    check = system_health_service._check_document_verification()
    assert check.status == "ok" and "latencyMs" in check.params
    assert sent["url"].endswith("/api/public/verify") and sent["body"] == {"sha256": "0" * 64}


def test_document_verification_check_fails_on_unexpected_answer_or_outage(clean_state, monkeypatch):
    monkeypatch.setattr(system_health_service.urllib.request, "urlopen", lambda *a, **k: _FakeResponse(b'{"found": true}'))
    checks = {check.key: check for check in system_health_service.collect_checks(clean_state, NOW)}
    assert checks["document_verification"].status == "critical" and "Unerwartete Antwort" in checks["document_verification"].error

    monkeypatch.setattr(system_health_service.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(ConnectionError("refused")))
    check = system_health_service._run_check("document_verification", system_health_service._check_document_verification)[0]
    problems = system_alert_service.derive_problems(_snapshot(checks=[check]), JobStatusOverview(items=[], generated_at=NOW), now=NOW)
    problem = next(item for item in problems if item.key == "check:document_verification")
    assert problem.severity == "critical" and problem.title == "Öffentliche Prüfseite nicht erreichbar"


# ── system_alert_service.derive_problems ─────────────────────────────────────────────────


def _jobs(db):
    from app.services.admin_job_status_service import AdminJobStatusService

    return AdminJobStatusService().get_overview(db, now=NOW)


def test_derive_problems_ignores_freshly_starting_containers(clean_state):
    snapshot = _snapshot(containers=[_container(health="starting", started_at=NOW - timedelta(minutes=2))])
    problems = system_alert_service.derive_problems(snapshot, _jobs(clean_state), now=NOW)
    assert [problem for problem in problems if problem.source != "job"] == []


def test_derive_problems_covers_containers_checks_jobs_and_stale_snapshot(clean_state):
    db = clean_state
    db.execute(text("SELECT record_job_run('export_cleanup', 'failure', now(), now(), 'OSError: disk full', TRUE)"))
    snapshot = _snapshot(
        containers=[_container("backend", health="unhealthy", health_output="TimeoutError: timed out")],
        checks=[HealthCheckRead(key="storage", status="critical", params={"freePercent": 3, "freeGb": 2, "totalGb": 80})],
        collected_at=NOW - timedelta(minutes=10),
    )

    problems = {problem.key: problem for problem in system_alert_service.derive_problems(
        snapshot, _jobs(db), now=NOW, restart_counts={"frontend": 4},
    )}

    assert problems["monitor:snapshot"].severity == "critical"
    assert (problems["container:backend"].reason, problems["container:backend"].severity) == ("unhealthy", "critical")
    assert "TimeoutError" in problems["container:backend"].message
    assert problems["container:frontend:restarts"].reason == "restart_loop"
    assert problems["check:storage"].title == "Speicherplatz knapp"
    assert (problems["job:export_cleanup"].reason, problems["job:export_cleanup"].severity) == ("failing", "warning")
    # Registrierte Loops ohne Lauf: Warnung (gemeldet erst nach der Schonfrist). Host-Cronjobs nie.
    assert problems["job:log_cleanup"].reason == "never_run"
    assert "job:backup_db" not in problems


# ── system_alert_service.evaluate_and_notify ─────────────────────────────────────────────


def test_problem_is_announced_only_after_grace_period_then_resolved(clean_state, sent):
    db = clean_state
    _enable_ntfy(db)
    unhealthy = _snapshot(containers=[_container(health="unhealthy")])

    system_alert_service.evaluate_and_notify(db, unhealthy, now=NOW)
    assert sent == []  # Karenzzeit: ein Deploy soll keinen Alarm auslösen
    system_alert_service.evaluate_and_notify(db, unhealthy, now=NOW + timedelta(seconds=120))
    assert [message.title for message in sent] == ["[hocX] Container backend ist unhealthy"]
    assert sent[0].click == "https://admin.example/admin/system"
    assert sent[0].priority == 4

    system_alert_service.evaluate_and_notify(db, _snapshot(collected_at=NOW + timedelta(seconds=150)), now=NOW + timedelta(seconds=150))
    assert sent[-1].title == "[hocX] Behoben: Container backend ist unhealthy"
    assert db.scalars(select(SystemAlertState)).all() == []
    kinds = [event.kind for event in db.scalars(select(SystemHealthEvent).order_by(SystemHealthEvent.id))]
    assert kinds == ["problem", "resolved"]


def test_problem_that_disappears_within_grace_period_leaves_no_trace(clean_state, sent):
    db = clean_state
    _enable_ntfy(db)
    system_alert_service.evaluate_and_notify(db, _snapshot(containers=[_container(health="unhealthy")]), now=NOW)
    system_alert_service.evaluate_and_notify(db, _snapshot(collected_at=NOW + timedelta(seconds=30)), now=NOW + timedelta(seconds=30))

    assert sent == []
    assert db.scalars(select(SystemHealthEvent)).all() == []


def test_escalation_and_reminder(clean_state, sent):
    db = clean_state
    _enable_ntfy(db)
    warning = _snapshot(checks=[HealthCheckRead(key="storage", status="warning", params={"freePercent": 10, "freeGb": 8, "totalGb": 80})])
    critical = _snapshot(checks=[HealthCheckRead(key="storage", status="critical", params={"freePercent": 3, "freeGb": 2, "totalGb": 80})])

    for offset in (0, 120):
        system_alert_service.evaluate_and_notify(db, warning.model_copy(update={"collected_at": NOW + timedelta(seconds=offset)}), now=NOW + timedelta(seconds=offset))
    system_alert_service.evaluate_and_notify(db, critical.model_copy(update={"collected_at": NOW + timedelta(seconds=150)}), now=NOW + timedelta(seconds=150))
    later = NOW + timedelta(hours=7)
    system_alert_service.evaluate_and_notify(db, critical.model_copy(update={"collected_at": later}), now=later)

    assert [message.title for message in sent] == [
        "[hocX] Speicherplatz knapp",
        "[hocX] Verschärft: Speicherplatz knapp",
        "[hocX] Weiterhin: Speicherplatz knapp",
    ]


def test_many_simultaneous_changes_are_sent_as_one_summary(clean_state, sent):
    db = clean_state
    _enable_ntfy(db)
    snapshot = _snapshot(containers=[_container(f"svc{index}", health="unhealthy") for index in range(7)])
    system_alert_service.evaluate_and_notify(db, snapshot, now=NOW)
    system_alert_service.evaluate_and_notify(db, snapshot.model_copy(update={"collected_at": NOW + timedelta(seconds=120)}), now=NOW + timedelta(seconds=120))

    assert len(sent) == 1
    assert sent[0].title == "[hocX] 7 Statusänderungen"
    assert sent[0].message.count("•") == 7


def test_events_are_recorded_even_without_ntfy(clean_state, sent):
    db = clean_state
    snapshot = _snapshot(containers=[_container(health="unhealthy")])
    system_alert_service.evaluate_and_notify(db, snapshot, now=NOW)
    system_alert_service.evaluate_and_notify(db, snapshot.model_copy(update={"collected_at": NOW + timedelta(seconds=120)}), now=NOW + timedelta(seconds=120))

    assert sent == []
    assert [event.kind for event in db.scalars(select(SystemHealthEvent))] == ["problem"]


def test_send_failure_is_kept_on_settings_and_logged_once(clean_state, monkeypatch):
    db = clean_state
    _enable_ntfy(db)

    def _fail(**_kwargs):
        raise ntfy_client.NtfyError("ntfy nicht erreichbar: connection refused")

    monkeypatch.setattr(ntfy_client, "send", _fail)
    logged = []
    monkeypatch.setattr(system_alert_service, "record_system_error", lambda db, *, exc: logged.append(exc))
    snapshot = _snapshot(containers=[_container(health="unhealthy")])
    for offset in (0, 120, 150):
        when = NOW + timedelta(seconds=offset)
        db.execute(text("DELETE FROM system_health_event"))
        db.execute(text("UPDATE system_alert_state SET notified_severity = NULL"))
        system_alert_service.evaluate_and_notify(db, snapshot.model_copy(update={"collected_at": when}), now=when)

    row = db.get(PlatformNotificationSettings, 1)
    assert row.last_send_error == "ntfy nicht erreichbar: connection refused"
    assert len(logged) == 1


# ── Einstellungen und Endpunkte ──────────────────────────────────────────────────────────


def test_notification_settings_validation_and_token_handling(clean_state):
    db = clean_state
    service = NotificationSettingsService()
    with pytest.raises(ValueError):
        service.update(db, NotificationSettingsWrite(ntfy_enabled=True, ntfy_server_url=None, ntfy_topic="x"))
    with pytest.raises(ValueError):
        service.update(db, NotificationSettingsWrite(ntfy_enabled=False, ntfy_server_url="ftp://ntfy.example"))
    with pytest.raises(ValueError):
        service.update(db, NotificationSettingsWrite(ntfy_enabled=False, ntfy_topic="mit leerzeichen"))

    result = service.update(db, NotificationSettingsWrite(
        ntfy_enabled=True, ntfy_server_url="https://ntfy.example/", ntfy_topic="hocx", ntfy_token="tk_secret",
    ))
    assert (result.ntfy_server_url, result.ntfy_token_set) == ("https://ntfy.example", True)
    row = db.get(PlatformNotificationSettings, 1)
    assert row.ntfy_token_encrypted and "tk_secret" not in row.ntfy_token_encrypted

    # None = unverändert, "" = entfernen
    assert service.update(db, NotificationSettingsWrite(ntfy_enabled=True, ntfy_server_url="https://ntfy.example", ntfy_topic="hocx")).ntfy_token_set
    assert not service.update(db, NotificationSettingsWrite(ntfy_enabled=True, ntfy_server_url="https://ntfy.example", ntfy_topic="hocx", ntfy_token="")).ntfy_token_set


def test_test_notification_route_reports_errors_instead_of_raising(clean_state, monkeypatch):
    db = clean_state
    _enable_ntfy(db)
    monkeypatch.setattr(ntfy_client, "send", lambda **_kwargs: (_ for _ in ()).throw(ntfy_client.NtfyError("HTTP 403")))

    result = admin_routes.send_test_notification(db=db, current_admin=_admin())

    assert (result.ok, result.error) == (False, "HTTP 403")


def test_summary_endpoint_requires_token_and_reports_status(clean_state, monkeypatch):
    db = clean_state
    token = admin_routes.rotate_status_token(db=db, current_admin=_admin()).status_token
    snapshots = {"current": _snapshot(collected_at=datetime.now(timezone.utc))}
    monkeypatch.setattr(system_health_service, "load_snapshot", lambda: snapshots["current"])

    with pytest.raises(HTTPException) as denied:
        system_status_routes.system_status_summary(_FakeRequest(), token="falsch", db=db)
    assert denied.value.status_code == 401

    ok = system_status_routes.system_status_summary(_FakeRequest({"authorization": f"Bearer {token}"}), token=None, db=db)
    assert ok.status_code == 200
    assert json.loads(ok.body)["status"] in ("ok", "warning")

    snapshots["current"] = _snapshot(collected_at=datetime.now(timezone.utc), containers=[_container(health="unhealthy")])
    critical = system_status_routes.system_status_summary(_FakeRequest(), token=token, db=db)
    assert (critical.status_code, json.loads(critical.body)["status"]) == (503, "critical")

    snapshots["current"] = None
    stale = system_status_routes.system_status_summary(_FakeRequest(), token=token, db=db)
    assert (stale.status_code, json.loads(stale.body)["status"]) == (503, "stale")


def test_system_status_route_combines_snapshot_problems_and_events(clean_state, monkeypatch):
    db = clean_state
    monkeypatch.setattr(system_health_service, "load_snapshot", lambda: _snapshot(collected_at=datetime.now(timezone.utc), containers=[_container(health="unhealthy")]))
    db.add(SystemHealthEvent(kind="container_restart", subject="container:backend", reason="restarted", severity="warning", title="t", message="m"))
    db.flush()

    result = admin_routes.get_system_status(db=db, current_admin=_admin())

    assert result.stale is False
    assert [problem.key for problem in result.problems if problem.source == "container"] == ["container:backend"]
    assert [event.kind for event in result.events] == ["container_restart"]


def test_never_run_is_announced_only_after_startup_grace_and_survives_restarts(clean_state, sent, monkeypatch):
    db = clean_state
    _enable_ntfy(db)

    class _OneNeverRun:
        def get_overview(self, db, *, now=None):
            from app.services.admin_job_status_service import AdminJobStatusService

            overview = AdminJobStatusService().get_overview(db, now=now)
            return overview.model_copy(update={"items": [item for item in overview.items if item.name == "log_cleanup"]})

    monkeypatch.setattr(system_alert_service, "AdminJobStatusService", _OneNeverRun)
    snapshot = _snapshot()
    for minutes in (0, 5, 20):
        when = NOW + timedelta(minutes=minutes)
        system_alert_service.evaluate_and_notify(db, snapshot.model_copy(update={"collected_at": when}), now=when)
    assert sent == []  # Schonfrist nach dem Start (30 min) noch nicht vorbei

    when = NOW + timedelta(minutes=31)
    system_alert_service.evaluate_and_notify(db, snapshot.model_copy(update={"collected_at": when}), now=when)
    assert [message.title for message in sent] == ["[hocX] Job log_cleanup ist noch nie gelaufen"]

    # Backend-Neustart: neue Schonfrist, aber das offene Problem wird nicht "behoben" gemeldet.
    monkeypatch.setattr(system_alert_service, "_PROCESS_STARTED_AT", when)
    later = when + timedelta(minutes=1)
    system_alert_service.evaluate_and_notify(db, snapshot.model_copy(update={"collected_at": later}), now=later)
    assert len(sent) == 1
