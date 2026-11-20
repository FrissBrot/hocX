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


class _RowsDb(_FakeDb):
    def __init__(self, rows) -> None:
        super().__init__()
        self.rows = rows

    def execute(self, statement):
        super().execute(statement)
        return self.rows


def test_original_checksum_counts_after_hocx_rewrote_the_file():
    """Schreibt hocX ein korrigiertes Aufnahmedatum in die Datei (Backend-Migration 0203), ändert
    sich checksum_sha256 - die ursprünglich abgegebene Datei bleibt trotzdem ein Duplikat."""
    db = _RowsDb([("neu", "original"), ("nur", None)])
    assert repository.list_checksums_for_element(db, assignment_id=1, event_id=2, list_entry_id=None) == {"neu", "original", "nur"}
    assert "stored_file.source_checksum_sha256" in db.sql.split("FROM", 1)[0]
