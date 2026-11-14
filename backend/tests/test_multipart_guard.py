"""Audit MAIN-SEC-004: Multipart-Bodies werden ohne gültige Session gar nicht erst gelesen
und sind in der Grösse begrenzt."""
from fastapi import FastAPI, File, UploadFile
from fastapi.testclient import TestClient

from app.core.admin_security import create_admin_session_token
from app.core.config import settings
from app.core.security import create_session_token
from app.multipart_guard import MultipartGuardMiddleware


def _app(calls: list[str]) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        MultipartGuardMiddleware,
        default_max_bytes=1024,
        path_limits=(("/api/big", 4096),),
        skip_prefixes=("/api/skip",),
    )

    for path in ("/api/upload", "/api/big", "/api/skip", "/api/admin/upload"):
        async def handler(file: UploadFile = File(...), _path=path):
            calls.append(_path)
            return {"size": len(await file.read())}

        app.post(path)(handler)
    return app


def test_unauthenticated_multipart_is_rejected_before_parsing():
    calls: list[str] = []
    client = TestClient(_app(calls))

    assert client.post("/api/upload", files={"file": ("a.bin", b"x" * 10)}).status_code == 401
    assert client.post(
        "/api/upload", files={"file": ("a.bin", b"x")}, cookies={settings.auth_session_cookie: "gefaelscht.abc"}
    ).status_code == 401
    assert calls == []


def test_skip_prefix_is_untouched():
    calls: list[str] = []
    client = TestClient(_app(calls))

    assert client.post("/api/skip", files={"file": ("a.bin", b"x" * 5000)}).status_code == 200
    assert calls == ["/api/skip"]


def test_size_limits_per_prefix():
    calls: list[str] = []
    client = TestClient(_app(calls))
    client.cookies.set(settings.auth_session_cookie, create_session_token(1, mfa_verified=True))

    assert client.post("/api/upload", files={"file": ("a.bin", b"x" * 100)}).status_code == 200
    assert client.post("/api/upload", files={"file": ("a.bin", b"x" * 2000)}).status_code == 413
    assert client.post("/api/big", files={"file": ("a.bin", b"x" * 2000)}).status_code == 200
    assert calls == ["/api/upload", "/api/big"]


def test_admin_paths_need_admin_session():
    calls: list[str] = []
    client = TestClient(_app(calls))

    user_cookie = {settings.auth_session_cookie: create_session_token(1, mfa_verified=True)}
    assert client.post("/api/admin/upload", files={"file": ("a.bin", b"x")}, cookies=user_cookie).status_code == 401
    admin_cookie = {settings.admin_session_cookie: create_admin_session_token(1, mfa_verified=True)}
    assert client.post("/api/admin/upload", files={"file": ("a.bin", b"x")}, cookies=admin_cookie).status_code == 200


def test_real_app_rejects_anonymous_csv_import():
    from app.main import app

    response = TestClient(app).post("/api/events/import-csv", files={"file": ("a.csv", b"x" * 10)})
    assert response.status_code == 401


def test_token_path_checks_the_access_token_before_parsing():
    """Persönlicher Abgabe-Link: Token im Header statt Session, geprüft vor dem Lesen des Bodys."""
    calls: list[str] = []
    checked: list[str] = []
    app = FastAPI()
    app.add_middleware(
        MultipartGuardMiddleware,
        default_max_bytes=1024,
        token_paths=(("/api/public/token-upload", "X-Access-Token", lambda token: checked.append(token) or token == "gut"),),
    )

    async def handler(file: UploadFile = File(...)):
        calls.append("token-upload")
        return {"size": len(await file.read())}

    app.post("/api/public/token-upload")(handler)
    client = TestClient(app)
    files = {"file": ("a.bin", b"x" * 10)}
    assert client.post("/api/public/token-upload", files=files).status_code == 404
    assert client.post("/api/public/token-upload", files=files, headers={"X-Access-Token": "falsch"}).status_code == 404
    assert calls == [] and checked == ["falsch"]
    assert client.post("/api/public/token-upload", files=files, headers={"X-Access-Token": "gut"}).json() == {"size": 10}
    # Grössenlimit gilt weiterhin
    assert client.post("/api/public/token-upload", files={"file": ("a.bin", b"x" * 4000)}, headers={"X-Access-Token": "gut"}).status_code == 413
