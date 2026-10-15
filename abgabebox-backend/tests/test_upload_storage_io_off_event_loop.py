"""S3-004: Seit dem Objektspeicher sind save_to_quarantine, move_from_quarantine und
delete_object bei S3 Netzwerk-Uploads/-Kopien mit Retries (bis 60 s Read-Timeout je Versuch).
Direkt in `async def upload()` aufgerufen, froren sie den ganzen uvicorn-Worker ein - alle
anderen Anfragen, auch Health und Status. Der Upload-Pfad muss sie darum über
asyncio.to_thread ausführen.

Wie test_tenant_storage_bytes_async.py ohne vollständige Tenant-/DB-/HTTP-Fixture: ein
Quelltext-Wächter gegen ein stilles Zurückfallen auf direkte Aufrufe.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
STORAGE_CALLS = {"save_to_quarantine", "move_from_quarantine", "delete_object"}


def _upload_function() -> ast.AsyncFunctionDef:
    tree = ast.parse((REPO_ROOT / "app" / "routes" / "public.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "upload":
            return node
    raise AssertionError("async def upload() nicht gefunden")


def test_upload_never_calls_object_storage_directly_on_the_event_loop():
    direct = [
        f"{node.func.id} (Zeile {node.lineno})"
        for node in ast.walk(_upload_function())
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in STORAGE_CALLS
    ]
    assert not direct, f"Direkte (blockierende) Speicheraufrufe in upload(): {direct}"


def test_upload_runs_every_storage_call_through_to_thread():
    threaded = {
        node.args[0].id
        for node in ast.walk(_upload_function())
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "to_thread"
        and node.args and isinstance(node.args[0], ast.Name)
    }
    assert STORAGE_CALLS <= threaded
