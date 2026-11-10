"""Concurrency-Audit CONC-002/-010: Datei- und Streaming-Antworten geben die DB-Verbindung frei,
bevor gesendet wird, und ein erschöpfter Pool führt schnell zu 503 statt zu langem Warten."""

import time

from fastapi import Depends, FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core import db as db_module
from app.core.db import engine, get_db, release_for_stream


def test_release_for_stream_returns_the_connection_before_streaming():
    seen_during_stream: list[int] = []
    app = FastAPI()

    @app.get("/download")
    def download(db=Depends(get_db)):
        db.execute(text("SELECT 1"))  # wie Auth-/Rechteprüfung vor dem Streamen

        def body():
            for _ in range(3):
                seen_during_stream.append(engine.pool.checkedout())
                time.sleep(0.05)
                yield b"x"

        return release_for_stream(db, StreamingResponse(body()))

    before = engine.pool.checkedout()
    with TestClient(app) as client:
        assert client.get("/download").content == b"xxx"
    assert seen_during_stream and max(seen_during_stream) == before


def test_pool_settings_come_from_config():
    from app.core.config import settings

    assert engine.pool.timeout() == settings.db_pool_timeout_seconds
    assert engine.pool.size() == settings.db_pool_size


def test_exhausted_pool_answers_503_quickly(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.config import settings
    from app.core.security import create_session_token
    from app.main import app

    tiny = create_engine(engine.url, pool_size=1, max_overflow=0, pool_timeout=0.5)
    monkeypatch.setattr(db_module, "SessionLocal", sessionmaker(bind=tiny))
    holder = tiny.connect()
    try:
        client = TestClient(app, raise_server_exceptions=False)  # ohne lifespan
        client.cookies.set(settings.auth_session_cookie, create_session_token(1))
        started = time.monotonic()
        response = client.get("/api/protocols")
        elapsed = time.monotonic() - started
        assert response.status_code == 503
        assert response.headers.get("Retry-After")
        assert response.json()["code"] == "db_busy"
        assert elapsed < 5
    finally:
        holder.close()
        tiny.dispose()
