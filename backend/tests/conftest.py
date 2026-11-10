import os

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


# --- RLS-Testmodus -------------------------------------------------------------------------
# HOCX_TEST_RLS=1 (zusammen mit APP_DATABASE_URL auf die Rolle hocx_app, sonst umgeht der
# Superuser jede Policy): jeder direkte Aufruf einer Routenfunktion aus app.api.routes läuft unter
# dem Mandanten des übergebenen CurrentUser, wie in Produktion nach get_optional_current_user.
# Setup und Prüfungen der Tests bleiben unbeschränkt. So prüft die ganze bestehende Suite, dass
# die Row-Level-Security (Migration 0132_tenant_rls) keine Funktion bricht.
if os.environ.get("HOCX_TEST_RLS") == "1":
    import functools
    import importlib
    import inspect
    import pkgutil

    import app.api.routes as _routes_package
    from app.core.security import CurrentUser
    from app.core.tenant_scope import _apply as _apply_scope
    from app.core.tenant_scope import bind_tenant_scope, bound_tenant_id

    def _scope_args(args, kwargs):
        values = [*args, *kwargs.values()]
        user = next((value for value in values if isinstance(value, CurrentUser)), None)
        session = next((value for value in values if isinstance(value, Session)), None)
        return user, session

    _UNCHANGED = object()

    def _enter(session: Session, user: CurrentUser):
        previous = bound_tenant_id(session)
        if previous == user.current_tenant_id:
            return _UNCHANGED  # verschachtelter Aufruf innerhalb derselben "Anfrage"
        # Frische Sicht wie in einer neuen Anfrage: nichts aus der Identity-Map des Setups.
        session.flush()
        session.expire_all()
        bind_tenant_scope(session, user.current_tenant_id)
        return previous

    def _leave(session: Session, previous) -> None:
        if previous is _UNCHANGED:
            return
        try:
            bind_tenant_scope(session, previous)
            # Die äussere Testtransaktion endet nie (anders als in Produktion, wo set_config(...,
            # true) mit dem Commit verfällt) - deshalb auch ausserhalb einer Session-Transaktion
            # direkt auf der Verbindung zurücksetzen.
            _apply_scope(session.connection(), previous)
        except Exception:  # abgebrochene Transaktion: der Test räumt selbst auf
            if previous is None:
                session.info.pop("rls_tenant_id", None)

    def _wrap(function):
        if inspect.iscoroutinefunction(function):
            @functools.wraps(function)
            async def async_wrapper(*args, **kwargs):
                user, session = _scope_args(args, kwargs)
                if user is None or session is None:
                    return await function(*args, **kwargs)
                previous = _enter(session, user)
                try:
                    return await function(*args, **kwargs)
                finally:
                    _leave(session, previous)

            return async_wrapper

        @functools.wraps(function)
        def wrapper(*args, **kwargs):
            user, session = _scope_args(args, kwargs)
            if user is None or session is None:
                return function(*args, **kwargs)
            previous = _enter(session, user)
            try:
                return function(*args, **kwargs)
            finally:
                _leave(session, previous)

        return wrapper

    for _module_info in pkgutil.iter_modules(_routes_package.__path__):
        _module = importlib.import_module(f"{_routes_package.__name__}.{_module_info.name}")
        for _name, _value in list(vars(_module).items()):
            if inspect.isfunction(_value) and _value.__module__ == _module.__name__ and not _name.startswith("__"):
                setattr(_module, _name, _wrap(_value))
