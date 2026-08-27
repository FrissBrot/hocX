from __future__ import annotations

import asyncio


def scan_bytes(content: bytes, *, host: str, port: int = 3310) -> str:
    """Scan file bytes via clamd stream. Returns 'clean', 'infected', or 'pending'.

    'pending' is returned when clamd is unreachable — the file is quarantined for later
    rescanning by the main backend. This prevents a clamd outage from blocking all uploads.

    This is a plain blocking call (pyclamd.ClamdNetworkSocket uses a raw synchronous socket,
    with up to a 30s timeout per call) - never call this directly from an `async def` route.
    Use scan_many() below, which runs each call off the event loop via asyncio.to_thread.
    """
    try:
        import pyclamd
        cd = pyclamd.ClamdNetworkSocket(host=host, port=port, timeout=30)
        result = cd.scan_stream(content)
        # result is None when clean; {'stream': ('FOUND', 'VirusName')} when infected
        return "clean" if result is None else "infected"
    except Exception:
        return "pending"


# (Critical, audit finding 2026-08-27): routes/public.py's upload() is an `async def` served by
# uvicorn (--workers 2, docker-compose.yml) - one event loop per worker, shared by every tenant's
# and every other endpoint's in-flight requests on that worker. scan_bytes() above used to be
# called directly from there, so a single scan (up to a 30s clamd timeout) froze that ENTIRE
# worker for its duration, not just the uploading request - a slow/unresponsive clamd could stall
# every other request landing on that worker. asyncio.to_thread moves the blocking call onto a
# worker thread, leaving the event loop free. A small bounded semaphore (not unlimited
# gather/asyncio.to_thread per file) keeps a single large batch from opening dozens of concurrent
# clamd connections at once; the real ceiling on batch size is the separate hard cap on files per
# request in routes/public.py (settings.max_files_per_upload_request), which this function does
# not itself enforce.
_SCAN_CONCURRENCY = 4


async def scan_many(contents: list[bytes], *, host: str, port: int = 3310) -> list[str]:
    """Scans multiple files concurrently (bounded by _SCAN_CONCURRENCY), each off the event loop
    via asyncio.to_thread. Returns results in the same order as `contents`."""
    semaphore = asyncio.Semaphore(_SCAN_CONCURRENCY)

    async def _scan_one(content: bytes) -> str:
        async with semaphore:
            return await asyncio.to_thread(scan_bytes, content, host=host, port=port)

    return await asyncio.gather(*(_scan_one(content) for content in contents))
