"""Synchrone Arbeit aus dem Event-Loop eines uvicorn-Workers heraushalten (Concurrency-Audit
CONC-001).

Ein synchroner DB-Aufruf in einer async-Funktion blockiert den ganzen Worker - alle Requests,
WebSockets und Hintergrund-Loops - bis er fertig ist, bei erschöpftem Pool bis pool_timeout.

- ``run_sync(fn, ...)``: sync-Funktion im Threadpool (wie ``run_in_threadpool``).
- ``run_coroutine_in_thread(fn, ...)``: eine async-Funktion, die DB-Zugriffe mit ``await``s
  mischt (Upload-Pipeline: ClamAV, GPS, HEIC), in einem Worker-Thread mit eigenem Event-Loop.
  Dort blockieren die DB-Aufrufe nur diesen Thread. Die Session wird nie gleichzeitig benutzt:
  der Aufrufer wartet. Nicht für den Typst-Renderer verwenden - dessen Compile-Slots gelten je
  Event-Loop (documents/renderer.py).

Funktionen, die ausschliesslich so (oder im Ingest-Thread) laufen, tragen an der def-Zeile
``# loop-ok: ...`` (scripts/check-security-rules.py, Regel blocking-db-in-async).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from starlette.concurrency import run_in_threadpool

T = TypeVar("T")


async def run_sync(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    return await run_in_threadpool(fn, *args, **kwargs)


async def run_coroutine_in_thread(fn: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any) -> T:
    def runner() -> T:
        return asyncio.run(fn(*args, **kwargs))

    return await run_in_threadpool(runner)
