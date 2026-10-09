import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.db import engine


@pytest.fixture
def db():
    """Session in einer aeusseren Transaktion, die am Ende immer zurueckgerollt wird - gleiches
    Muster wie backend/tests/conftest.py. Code unter Test darf normal committen; das gibt nur
    den inneren SAVEPOINT frei."""
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
    """Importiert das Test-Fixture-Wegenetz (tests/fixtures/routing_network_sample.geojson)
    einmal pro Testlauf. Laeuft bewusst AUSSERHALB der pro-Test-SAVEPOINT-Transaktion der
    `db`-Fixture: scripts/import_routing_network.py verwendet eine eigene Admin-Verbindung mit
    echtem COMMIT, das importierte Netz bleibt also fuer die ganze Session bestehen."""
    from pathlib import Path

    from scripts.import_routing_network import import_network

    import_network(
        Path(__file__).parent / "fixtures" / "routing_network_sample.geojson",
        "Test-Fixture (pytest session scope)",
    )
