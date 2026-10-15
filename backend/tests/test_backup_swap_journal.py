"""Zustandsmatrix für den Datenbanktausch des Voll-Restores (BORG-002).

Für jeden Absturzzeitpunkt (Journal-Schritt × tatsächlich vorhandene Datenbanken) muss
reconcile_swap danach eine erreichbare Live-Datenbank mit eindeutigem Inhalt hinterlassen,
nie eine Datenbank löschen und unklare Zustände nur melden (Schritt inconsistent)."""

from __future__ import annotations

import json
import uuid

import pytest

from app.backup import run_restore
from app.backup.pgtools import PgTarget, PgTools
from app.backup.run_restore import reconcile_swap
from app.core.config import settings

# Inhalte: "old" = bisherige Live-DB, "new" = wiederhergestellte DB.
CASES = [
    # (Journal-Schritt, vorhandene DBs {Rolle: Inhalt}, erwarteter Schritt danach, Inhalt von live danach)
    ("copied", {"live": "old", "restored": "new"}, None, "old"),
    ("renaming_live", {"live": "old", "restored": "new"}, None, "old"),
    # Absturz nach live -> pre (Audit Fall 1, auch mit dem alten Journalformat "copied"/"renamed_live")
    ("renaming_live", {"pre": "old", "restored": "new"}, None, "old"),
    ("copied", {"pre": "old", "restored": "new"}, None, "old"),
    ("renamed_live", {"pre": "old", "restored": "new"}, None, "old"),
    ("renaming_restored", {"pre": "old", "restored": "new"}, None, "old"),
    # Absturz nach restored -> live, Journal noch nicht nachgezogen (Audit Fall 2)
    ("renaming_restored", {"pre": "old", "live": "new"}, "renamed_restored", "new"),
    ("renamed_live", {"pre": "old", "live": "new"}, "renamed_restored", "new"),
    ("renamed_restored", {"pre": "old", "live": "new"}, "renamed_restored", "new"),
    # Rücktausch (Audit Fall 3)
    ("rolling_back", {"live": "new", "pre": "old"}, "rolling_back", "new"),
    ("rolling_back", {"failed": "new", "pre": "old"}, "rolled_back", "old"),
    ("rolling_back", {"live": "old", "failed": "new"}, "rolled_back", "old"),
    ("rolled_back", {"live": "old", "failed": "new"}, "rolled_back", "old"),
    # Unklare Zustände: nichts umbenennen, nichts löschen
    ("copied", {"live": "old", "restored": "new", "pre": "old"}, "inconsistent", "old"),
    ("renaming_live", {"restored": "new"}, "inconsistent", None),
    ("renamed_restored", {"live": "new"}, "inconsistent", "new"),
    ("rolling_back", {"pre": "old"}, "inconsistent", "old"),
    ("unbekannt", {"live": "old"}, "inconsistent", "old"),
]


def _names() -> dict[str, str]:
    suffix = uuid.uuid4().hex[:8]
    return {role: f"hocx_sw{role[:4]}_{suffix}" for role in ("live", "restored", "pre", "failed")}


def _create(pg: PgTools, name: str, content: str) -> None:
    pg.create_database(name)
    pg.psql(f"CREATE TABLE marker (name text); INSERT INTO marker VALUES ('{content}');", database=name)
    pg.psql(f'ALTER DATABASE "{name}" WITH ALLOW_CONNECTIONS false;', database="postgres")


def _allows_connections(pg: PgTools, name: str) -> bool:
    return pg.psql(f"SELECT datallowconn FROM pg_database WHERE datname = '{name}';", database="postgres") == "t"


def _drop_all(pg: PgTools, names: dict[str, str]) -> None:
    for name in names.values():
        if pg.database_exists(name):
            pg.psql(f'ALTER DATABASE "{name}" WITH ALLOW_CONNECTIONS true;', database="postgres")
            pg.drop_database(name)


@pytest.mark.parametrize(("step", "existing", "expected_step", "live_content"), CASES)
def test_reconcile_swap_leaves_a_reachable_live_database(step, existing, expected_step, live_content):
    names = _names()
    journal = {"job_id": "test", "live": names["live"], "restored": names["restored"], "pre": names["pre"], "step": step}
    if step in run_restore.ROLLBACK_STEPS:
        journal["failed"] = names["failed"]
    with PgTools(PgTarget.from_url(settings.database_url)) as pg:
        try:
            for role, content in existing.items():
                _create(pg, names[role], content)
            result, actions = reconcile_swap(pg, journal)
            assert (result["step"] if result else None) == expected_step, actions
            # Nie eine Datenbank verloren: Anzahl unverändert.
            assert sum(pg.database_exists(n) for n in names.values()) == len(existing)
            if live_content is None:
                assert not pg.database_exists(names["live"])
            else:
                assert _allows_connections(pg, names["live"])
                assert pg.psql("SELECT name FROM marker;", database=names["live"]) == live_content
            if expected_step is None:
                # Tausch beginnt neu: bisheriger Stand ist live, Restore-DB noch vorhanden, pre frei.
                assert pg.database_exists(names["restored"]) and not pg.database_exists(names["pre"])
            if expected_step == "renamed_restored":
                assert pg.database_exists(names["pre"]) and not pg.database_exists(names["restored"])
        finally:
            _drop_all(pg, names)


def test_reconcile_swap_is_idempotent():
    names = _names()
    journal = {"job_id": "test", "live": names["live"], "restored": names["restored"], "pre": names["pre"], "step": "renaming_restored"}
    with PgTools(PgTarget.from_url(settings.database_url)) as pg:
        try:
            _create(pg, names["pre"], "old")
            _create(pg, names["live"], "new")
            first, _ = reconcile_swap(pg, journal)
            second, actions = reconcile_swap(pg, first)
            assert first == second and second["step"] == "renamed_restored" and actions == []
        finally:
            _drop_all(pg, names)


def test_worker_start_recovery_rewrites_the_journal_from_the_database_state(tmp_path):
    """recover_interrupted_cutover schreibt das Ergebnis zurück: ein vollzogener Tausch wird als
    renamed_restored vermerkt (der Auftrag springt dann in den Smoke-Test, kein zweiter Tausch)."""
    from types import SimpleNamespace

    names = _names()
    journal_dir = tmp_path / "restore-journal"
    journal_dir.mkdir()
    path = journal_dir / "job.json"
    path.write_text(json.dumps({"job_id": "job", "live": names["live"], "restored": names["restored"], "pre": names["pre"],
                                "step": "renaming_restored"}))
    env = SimpleNamespace(config=SimpleNamespace(work_dir=tmp_path), database_url=settings.database_url)
    with PgTools(PgTarget.from_url(settings.database_url)) as pg:
        try:
            _create(pg, names["pre"], "old")
            _create(pg, names["live"], "new")
            actions = run_restore.recover_interrupted_cutover(env)
            assert any("vollzogen" in a for a in actions)
            assert json.loads(path.read_text())["step"] == "renamed_restored"
            assert _allows_connections(pg, names["live"])
        finally:
            _drop_all(pg, names)


def test_cleanup_after_failure_never_drops_databases_while_a_swap_journal_exists(tmp_path, monkeypatch):
    from types import SimpleNamespace

    job = SimpleNamespace(id=uuid.uuid4(), checkpoint={"restore_db": "hocx_restore_x", "generation": 7, "profile_id": 1})
    (tmp_path / "restore-journal").mkdir()
    (tmp_path / "restore-journal" / f"{job.id.hex}.json").write_text("{}")
    env = SimpleNamespace(config=SimpleNamespace(work_dir=tmp_path, staging_dir=tmp_path), database_url=settings.database_url)
    dropped: list[str] = []
    monkeypatch.setattr(PgTools, "drop_database", lambda self, name: dropped.append(name))
    run_restore.cleanup_failed_full_restore(env, db=None, job=job)  # type: ignore[arg-type]
    assert dropped == []
