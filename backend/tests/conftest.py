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


@pytest.fixture(scope="session", autouse=True)
def _dev_document_signing(tmp_path_factory):
    """Test-Stack und CI nutzen automatisch ein Dev-Signaturzertifikat (wie
    scripts/generate-dev-signing-cert.sh), sofern keines konfiguriert ist - ohne bricht der
    App-Start im Produktionsmodus ab (main.py lifespan)."""
    from app.core.config import settings
    from app.documents import signing
    from app.documents.devcert import generate

    if signing.signing_configured():
        yield
        return
    key_path, cert_path = generate(tmp_path_factory.mktemp("signing"))
    settings.document_signing_key_path = str(key_path)
    settings.document_signing_cert_path = str(cert_path)
    signing.reset_signer_cache()
    yield
    settings.document_signing_key_path = None
    settings.document_signing_cert_path = None
    signing.reset_signer_cache()
