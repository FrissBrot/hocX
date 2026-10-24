# GENERIERT aus backend/app/scanner.py - nicht von Hand bearbeiten, siehe scripts/sync-objstore-client.sh
from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path

_SCAN_CONCURRENCY = 4
# Höchstens so viele gleichzeitige ClamAV-Verbindungen je Prozess, über alle Requests und Jobs
# hinweg (Concurrency-Audit CONC-013). clamd hat MaxThreads 3/MaxQueue 32 für alle Dienste
# zusammen; 4 je Request und Batch liessen die Warteschlange im Upload-Sturm überlaufen.
PROCESS_SCAN_SLOTS = threading.BoundedSemaphore(2)
# Länger auf einen Slot zu warten lohnt nicht: die Datei bleibt dann "pending" (Quarantäne bzw.
# Nachscan durch upload_pipeline_rescan/abgabebox_rescan), statt einen Thread festzuhalten.
SLOT_WAIT_SECONDS = 120
MAX_SCAN_BYTES = 100 * 1024**2
_logger = logging.getLogger(__name__)


def _scan(content, *, host: str, port: int) -> str:
    if not PROCESS_SCAN_SLOTS.acquire(timeout=SLOT_WAIT_SECONDS):
        _logger.warning("Kein ClamAV-Slot frei nach %s s - Datei bleibt pending", SLOT_WAIT_SECONDS)
        return "pending"
    try:
        return _scan_unbounded(content, host=host, port=port)
    finally:
        PROCESS_SCAN_SLOTS.release()


def _scan_unbounded(content, *, host: str, port: int) -> str:
    import pyclamd
    try:
        result = pyclamd.ClamdNetworkSocket(host=host, port=port, timeout=60).scan_stream(content)
        if result is None:
            return "clean"
        if any(status == "FOUND" and not reason.startswith("Heuristics.Limits.Exceeded") for status, reason in result.values()):
            return "infected"
        _logger.error("ClamAV konnte die Datei nicht prüfen: %s", result)
        return "error"
    except pyclamd.BufferTooLongError:
        return "error"
    except Exception:
        _logger.warning("ClamAV vorübergehend nicht erreichbar", exc_info=True)
        return "pending"


def scan_bytes(content: bytes, *, host: str, port: int = 3310) -> str:
    """Nur Verbindungsfehler bleiben pending; Scanfehler sind keine Virenfunde."""
    if len(content) > MAX_SCAN_BYTES:
        return "error"
    return _scan(content, host=host, port=port)


def scan_file(path: str | Path, *, host: str, port: int = 3310) -> str:
    try:
        path = Path(path)
        if path.stat().st_size > MAX_SCAN_BYTES:
            return "error"
        with path.open("rb") as source:
            return _scan(source, host=host, port=port)
    except OSError:
        return "error"


async def scan_many(contents: list[bytes], *, host: str, port: int = 3310) -> list[str]:
    semaphore = asyncio.Semaphore(_SCAN_CONCURRENCY)
    async def scan_one(content: bytes) -> str:
        async with semaphore:
            return await asyncio.to_thread(scan_bytes, content, host=host, port=port)
    return await asyncio.gather(*(scan_one(content) for content in contents))
