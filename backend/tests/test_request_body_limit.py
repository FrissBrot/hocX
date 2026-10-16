"""MAIN-OPS-013: JSON- und andere Bodies ausser Multipart sind im Backend begrenzt (das Limit
liegt bewusst nicht in Traefik, dessen Buffering auch Antworten puffert)."""
from fastapi import FastAPI, File, Request, UploadFile
from fastapi.testclient import TestClient

from app.request_body_limit import RequestBodyLimitMiddleware


def _client() -> TestClient:
    app = FastAPI()
    app.add_middleware(RequestBodyLimitMiddleware, max_bytes=100, skip_prefixes=("/api/skip",))

    @app.post("/api/json")
    async def json_route(request: Request):
        return {"size": len(await request.body())}

    @app.post("/api/skip")
    async def skip_route(request: Request):
        return {"size": len(await request.body())}

    @app.post("/api/upload")
    async def upload_route(file: UploadFile = File(...)):
        return {"size": len(await file.read())}

    return TestClient(app)


def test_small_json_passes_and_large_json_is_rejected():
    client = _client()
    assert client.post("/api/json", content=b"x" * 100).json() == {"size": 100}
    assert client.post("/api/json", content=b"x" * 101).status_code == 413


def test_chunked_body_without_length_is_counted():
    client = _client()

    def chunks():
        for _ in range(5):
            yield b"x" * 40

    assert client.post("/api/json", content=chunks()).status_code == 413


def test_multipart_and_skipped_paths_are_left_to_their_own_limits():
    client = _client()
    assert client.post("/api/upload", files={"file": ("a.bin", b"x" * 500)}).json() == {"size": 500}
    assert client.post("/api/skip", content=b"x" * 500).json() == {"size": 500}
