"""Synchrone DB-Arbeit aus dem Event-Loop heraushalten (Concurrency-Audit CONC-001), Gegenstück
zu backend/app/core/offload.py. ``run_coroutine_in_thread`` führt eine async-Funktion, die
DB-Zugriffe mit ``await``s mischt, in einem Worker-Thread mit eigenem Event-Loop aus - dort
blockieren die DB-Aufrufe nur diesen Thread, nie den ganzen Worker."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from starlette.concurrency import run_in_threadpool

T = TypeVar("T")


async def run_coroutine_in_thread(fn: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any) -> T:
    def runner() -> T:
        return asyncio.run(fn(*args, **kwargs))

    return await run_in_threadpool(runner)
