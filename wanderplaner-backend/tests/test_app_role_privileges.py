"""Least-Privilege der Laufzeitrolle wanderplaner_app (alembic/versions/0001_initial.py).
Die uebrigen Tests laufen wie in hocX mit der Admin-Rolle, weil ihre Fixtures Wegenetz und
Umgebungsdaten schreiben; dieser Test prueft die Rechte der App-Rolle gezielt."""

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError

APP_URL = os.environ.get("WANDERPLANER_TEST_APP_DATABASE_URL")

pytestmark = pytest.mark.skipif(not APP_URL, reason="WANDERPLANER_TEST_APP_DATABASE_URL nicht gesetzt")


@pytest.fixture
def app_connection():
    engine = create_engine(APP_URL)
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()
    engine.dispose()


def test_app_role_may_write_tours(app_connection):
    tour_id = app_connection.execute(text(
        "INSERT INTO hiking_tour (tenant_id, title) VALUES (1, 'Rechte-Test') RETURNING id"
    )).scalar_one()
    app_connection.execute(text(
        "INSERT INTO hiking_tour_waypoint (hiking_tour_id, sequence, kind, point) "
        "VALUES (:id, 0, 'START', ST_SetSRID(ST_MakePoint(8.5, 47.0), 4326))"
    ), {"id": tour_id})
    app_connection.execute(text("DELETE FROM hiking_tour WHERE id = :id"), {"id": tour_id})


@pytest.mark.parametrize("table", ["routing_edge", "routing_network_meta", "hiking_landmark", "hiking_landmark_import"])
def test_app_role_may_only_read_reference_data(app_connection, table):
    app_connection.execute(text(f"SELECT count(*) FROM {table}"))
    with pytest.raises(ProgrammingError, match="permission denied"):
        app_connection.execute(text(f"DELETE FROM {table}"))
