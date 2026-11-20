"""Termine einer Termin-Abgabe kommen in derselben Grundreihenfolge wie im Hauptbackend
(Nachtlauf 2026-11-20).

SubmissionRepository.list_events_by_tag im Hauptbackend sortiert nach event_date, id; die
sort_order der Abgabe (alphabetisch, Nähe, Datum) sortiert danach stabil und lässt
Gleichstände in dieser Reihenfolge. Die Abgabebox las die Termine ohne ORDER BY: bei
Gleichstand (alphabetisch bei lauter «Hock»-Terminen, Nähe bei -3/+3 Tagen) erschienen sie
in Heap-Reihenfolge, also anders als in der Verwaltung, die genau diese Reihenfolge verspricht."""
from __future__ import annotations

from app import repository


class _FakeDb:
    def __init__(self) -> None:
        self.sql = ""

    def execute(self, statement):
        self.sql = str(statement.compile(compile_kwargs={"literal_binds": True}))

        class _Result:
            def mappings(self):
                return iter([])

        return _Result()


def test_events_are_ordered_like_in_the_main_backend():
    db = _FakeDb()
    repository.list_events_by_tag(db, tenant_id=1, tag="Hock")
    assert "ORDER BY event.event_date ASC, event.id ASC" in db.sql


def test_cycle_filtered_events_are_ordered_too():
    db = _FakeDb()
    repository.list_events_by_tag(db, tenant_id=1, tag="Hock", cycle_config_id=3, cycle_years={2026})
    assert db.sql.rstrip().endswith("ORDER BY event.event_date ASC, event.id ASC")
