from __future__ import annotations

import asyncio
import logging
from pathlib import Path

_SCAN_CONCURRENCY = 4
MAX_SCAN_BYTES = 100 * 1024**2
_logger = logging.getLogger(__name__)


def _scan(content, *, host: str, port: int) -> str:
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
