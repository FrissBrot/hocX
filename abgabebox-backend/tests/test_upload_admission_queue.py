"""CONC-007: Upload-Annahme der Abgabebox - nur Upload-Pfade zählen, Uploads warten auf einen
freien Platz statt sofort 503 zu bekommen."""
import asyncio

from app.upload_admission import UploadAdmissionMiddleware

UPLOAD = "/api/public/tok/assignments/a/elements/e/upload"
CAPTCHA = "/api/public/tok/assignments/a/elements/e/captcha-verify"


def _scope(path: str) -> dict:
    return {"type": "http", "method": "POST", "path": path, "headers": [(b"content-length", b"10")]}


async def _receive():
    return {"type": "http.request", "body": b"", "more_body": False}


def _run(middleware, paths):
    statuses = []

    async def call(path):
        async def send(message):
            if message["type"] == "http.response.start":
                statuses.append((path, message["status"]))
        await middleware(_scope(path), _receive, send)

    async def scenario():
        await asyncio.gather(*(call(path) for path in paths))

    asyncio.run(scenario())
    return statuses


def _app(active: list, peak: list, delay: float = 0.1):
    async def app(scope, receive, send):
        active.append(1)
        peak.append(len(active))
        await asyncio.sleep(delay)
        active.pop()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})
    return app


def test_uploads_queue_instead_of_503_and_respect_the_limit():
    active, peak = [], []
    middleware = UploadAdmissionMiddleware(_app(active, peak), path="/api/public/", path_suffix="/upload", max_bytes=100, max_active=2, wait_seconds=5)
    statuses = _run(middleware, [UPLOAD] * 6)
    assert [status for _, status in statuses] == [200] * 6
    assert max(peak) == 2


def test_waiting_too_long_returns_503_with_retry_after():
    active, peak = [], []
    middleware = UploadAdmissionMiddleware(_app(active, peak, delay=0.5), path="/api/public/", path_suffix="/upload", max_bytes=100, max_active=1, wait_seconds=0.1)
    statuses = sorted(status for _, status in _run(middleware, [UPLOAD, UPLOAD]))
    assert statuses == [200, 503]


def test_captcha_and_verify_are_never_held_back_by_uploads():
    active, peak = [], []
    middleware = UploadAdmissionMiddleware(_app(active, peak, delay=0.3), path="/api/public/", path_suffix="/upload", max_bytes=100, max_active=1, wait_seconds=0)
    statuses = dict(_run(middleware, [UPLOAD, CAPTCHA, "/api/public/verify"]))
    assert statuses == {UPLOAD: 200, CAPTCHA: 200, "/api/public/verify": 200}


def test_non_upload_posts_keep_a_small_size_limit():
    active, peak = [], []
    middleware = UploadAdmissionMiddleware(_app(active, peak), path="/api/public/", path_suffix="/upload", max_bytes=10_000, small_max_bytes=5)
    statuses = dict(_run(middleware, [CAPTCHA]))
    assert statuses == {CAPTCHA: 413}


def test_exhausted_pool_answers_503_with_retry_after():
    from sqlalchemy.exc import TimeoutError as PoolTimeout

    from app.main import db_pool_timeout_handler

    response = asyncio.run(db_pool_timeout_handler(None, PoolTimeout("QueuePool limit")))
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "5"
