"""Duplikatprüfung nur gegen Dateien, die wirklich angekommen sind (Nachtlauf 2026-11-20).

upload() quittiert eine Datei, deren SHA-256 im Element schon vorkommt, still als Erfolg und
speichert sie nicht. list_checksums_for_element lieferte dafür auch Dateien, deren Nachscan
gescheitert ist (scan_status 'error': in der Verwaltung dauerhaft gesperrt, kein erneuter Scan)
oder die als Schadware eingestuft wurden. Gab die Person auf Bitte des Vereins dieselbe Datei
noch einmal ab, sah sie «erfolgreich», gespeichert wurde nichts."""
from __future__ import annotations

from app import repository


class _FakeDb:
    def __init__(self) -> None:
        self.sql = ""

    def execute(self, statement):
        self.sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        return []


def test_failed_or_infected_files_do_not_count_as_already_submitted():
    db = _FakeDb()
    assert repository.list_checksums_for_element(db, assignment_id=1, event_id=2, list_entry_id=None) == set()
    where = db.sql.split("WHERE", 1)[1]
    assert "coalesce(stored_file.scan_status, 'clean') NOT IN ('error', 'infected')" in where
