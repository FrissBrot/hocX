"""Obergrenze für CSV-Importe (Termine, Personen).

Ohne Grenze wurde eine CSV-Datei bis zur Dateigrösse komplett verarbeitet: Hunderttausende Zeilen in
einer Transaktion (Termine inkl. Zyklus-Zuordnung und Foto-Abgleich je Termin) bzw. als JSON-Vorschau,
was einen Worker-Thread lange bindet (Nachtlauf 2026-11-19). Vereine importieren realistisch einige
hundert Zeilen; grössere Bestände lassen sich aufteilen.
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import TypeVar

MAX_CSV_IMPORT_ROWS = 2000

T = TypeVar("T")


class CsvTooManyRows(ValueError):
    """Erwartete Ablehnung (ValueError-Konvention); Route antwortet 400 mit Code und Parameter."""

    code = "csv_too_many_rows"

    def __init__(self, limit: int = MAX_CSV_IMPORT_ROWS) -> None:
        super().__init__(f"Die CSV-Datei hat zu viele Zeilen (höchstens {limit} Datenzeilen). Bitte aufteilen und in mehreren Schritten importieren.")
        self.limit = limit

    def detail(self) -> dict:
        return {"code": self.code, "message": str(self), "params": {"max": self.limit}}


def limit_csv_rows(rows: Iterable[T], limit: int = MAX_CSV_IMPORT_ROWS) -> Iterator[T]:
    """Reicht höchstens `limit` Datenzeilen durch; eine weitere Zeile bricht mit CsvTooManyRows ab
    (bevor sie verarbeitet wird)."""
    for count, row in enumerate(rows, start=1):
        if count > limit:
            raise CsvTooManyRows(limit)
        yield row
