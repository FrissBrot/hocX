import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.db import engine


@pytest.fixture
def db():
    """A session bound to a connection wrapped in an outer transaction that's always
    rolled back at teardown. This runs against the same database the app itself uses
    (no separate test DB/container - see project decision to not stand up new test
    infra) but no test can ever leave a row behind: the code under test is free to call
    Session.commit() as usual, which only releases the inner SAVEPOINT (immediately
    reopened below), while the real COMMIT never happens until the outer transaction
    is rolled back here.
    """
    connection = engine.connect()
    outer_transaction = connection.begin()
    session = Session(bind=connection, autoflush=False, future=True)
    session.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(sess, transaction):
        if transaction.nested and not transaction._parent.nested:
            sess.begin_nested()

    try:
        yield session
    finally:
        session.close()
        outer_transaction.rollback()
        connection.close()


@pytest.fixture(scope="session")
def routing_network():
    """Importiert das Wanderplaner-Test-Fixture-Wegenetz (tests/fixtures/
    routing_network_sample.geojson) einmal pro Testlauf. Laeuft bewusst AUSSERHALB der
    pro-Test-SAVEPOINT-Transaktion der `db`-Fixture oben: scripts/import_routing_network.py
    verwendet eine eigene Admin-Verbindung mit echtem COMMIT (siehe dessen Docstring - braucht
    TRUNCATE/DDL-nahe Rechte, die die eingeschraenkte App-Rolle nicht hat), das importierte
    Netz bleibt also fuer die ganze Session bestehen. Tests, die routing_service.py pruefen,
    deklarieren diese Fixture explizit als Parameter."""
    from pathlib import Path

    from scripts.import_routing_network import import_network

    import_network(
        Path(__file__).parent / "fixtures" / "routing_network_sample.geojson",
        "Test-Fixture (pytest session scope)",
    )
