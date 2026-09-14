from __future__ import annotations

import asyncio
from pathlib import Path

# Matches abgabebox-backend/app/scanner.py's concurrency bound - deliberately not a Setting,
# see that module's docstring for why 4 is the right number of concurrent clamd connections.
_SCAN_CONCURRENCY = 4


def scan_bytes(content: bytes, *, host: str, port: int = 3310) -> str:
    """Scan file bytes via clamd stream. Returns 'clean', 'infected', or 'pending'."""
    try:
        import pyclamd
        cd = pyclamd.ClamdNetworkSocket(host=host, port=port, timeout=30)
        result = cd.scan_stream(content)
        return "clean" if result is None else "infected"
    except Exception:
        return "pending"


def scan_file(path: str | Path, *, host: str, port: int = 3310) -> str:
    """Read file from disk and scan via clamd. Returns 'clean', 'infected', or 'pending'."""
    try:
        content = Path(path).read_bytes()
    except OSError:
        return "pending"
    return scan_bytes(content, host=host, port=port)


async def scan_many(contents: list[bytes], *, host: str, port: int = 3310) -> list[str]:
    """Scan multiple files concurrently without blocking the event loop. scan_bytes() itself
    is a blocking clamd call (up to the 30s timeout) - calling it directly from an async route
    handler freezes the whole uvicorn worker (every tenant, every request) for that long.
    asyncio.to_thread offloads each scan to a worker thread; the semaphore bounds how many
    clamd connections run at once. Independent implementation of the same pattern as
    abgabebox-backend/app/scanner.py::scan_many - deliberately not imported from there, see
    the upload-pipeline unification plan for why the two services don't share code."""
    semaphore = asyncio.Semaphore(_SCAN_CONCURRENCY)

    async def _scan_one(content: bytes) -> str:
        async with semaphore:
            return await asyncio.to_thread(scan_bytes, content, host=host, port=port)

    return await asyncio.gather(*(_scan_one(content) for content in contents))
