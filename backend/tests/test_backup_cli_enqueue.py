"""enqueue-backup (Backup vor dem Deploy, BORG-004): ein bereits offenes Backup führt nicht zu
einem Traceback, sondern wird abgewartet; "partial" ist mit --accept-partial ein Erfolg."""

from __future__ import annotations

import threading
import time
import uuid

import pytest
from sqlalchemy import delete, select, update

from app.backup.cli import main as cli_main
from app.backup.jobs import OPEN_JOB_STATES
from app.core.db import SessionLocal
from app.models import BackupJob


@pytest.fixture
def clean_backup_jobs():
    with SessionLocal() as db:
        db.execute(update(BackupJob).where(BackupJob.kind == "backup", BackupJob.state.in_(OPEN_JOB_STATES)).values(state="cancelled"))
        db.commit()
    created: list[uuid.UUID] = []
    yield created
    with SessionLocal() as db:
        db.execute(delete(BackupJob).where(BackupJob.id.in_(created)))
        db.execute(delete(BackupJob).where(BackupJob.idempotency_key.like("pre_deploy:cli-test-%")))
        db.commit()


def _add_job(created: list[uuid.UUID], **values) -> uuid.UUID:
    with SessionLocal() as db:
        job = BackupJob(kind="backup", trigger="manual", options={}, **values)
        db.add(job)
        db.commit()
        created.append(job.id)
        return job.id


def _set_state(job_id: uuid.UUID, state: str) -> None:
    with SessionLocal() as db:
        db.execute(update(BackupJob).where(BackupJob.id == job_id).values(state=state))
        db.commit()


def test_open_backup_without_wait_fails_cleanly(clean_backup_jobs, capsys):
    _add_job(clean_backup_jobs, state="running")
    assert cli_main(["enqueue-backup", "--trigger", "pre_deploy", "--key", f"cli-test-{uuid.uuid4().hex}"]) == 1
    assert "bereits" in capsys.readouterr().err


def test_open_backup_is_awaited_then_own_job_is_created(clean_backup_jobs, capsys):
    blocker = _add_job(clean_backup_jobs, state="running")
    key = f"cli-test-{uuid.uuid4().hex}"
    result: dict[str, int] = {}

    def run() -> None:
        result["rc"] = cli_main(["enqueue-backup", "--trigger", "pre_deploy", "--key", key, "--protect", "--wait",
                                 "--timeout", "30", "--poll-seconds", "0.2", "--accept-partial"])

    thread = threading.Thread(target=run)
    thread.start()
    time.sleep(1)
    _set_state(blocker, "completed")  # laufendes Backup endet
    own = None
    deadline = time.monotonic() + 15
    while own is None and time.monotonic() < deadline:
        with SessionLocal() as db:
            own = db.scalars(select(BackupJob).where(BackupJob.idempotency_key == f"pre_deploy:{key}")).first()
        time.sleep(0.2)
    assert own is not None and own.options.get("protected") is True
    _set_state(own.id, "partial")  # eigener Auftrag endet teilweise erfolgreich
    thread.join(timeout=20)
    assert result.get("rc") == 0
    assert "warte" in capsys.readouterr().err


@pytest.mark.parametrize(("accept", "expected"), [(True, 0), (False, 1)])
def test_partial_result_exit_code(clean_backup_jobs, accept, expected):
    key = f"cli-test-{uuid.uuid4().hex}"
    _add_job(clean_backup_jobs, state="partial", idempotency_key=f"pre_deploy:{key}")
    argv = ["enqueue-backup", "--trigger", "pre_deploy", "--key", key, "--wait", "--timeout", "5", "--poll-seconds", "0.1"]
    assert cli_main(argv + (["--accept-partial"] if accept else [])) == expected


def test_timeout_while_another_backup_runs_is_not_a_traceback(clean_backup_jobs):
    _add_job(clean_backup_jobs, state="running")
    argv = ["enqueue-backup", "--trigger", "pre_deploy", "--key", f"cli-test-{uuid.uuid4().hex}", "--wait", "--timeout", "1", "--poll-seconds", "0.2"]
    assert cli_main(argv) == 1
