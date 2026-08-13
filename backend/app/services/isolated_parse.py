from __future__ import annotations

import multiprocessing as mp
import queue as queue_module
import sys
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.word_import_service import ParsedDocx

# Hard resource limits for parsing an untrusted uploaded .docx/.pdf, applied inside the
# child process (not the request-serving worker) - see parse_document_isolated below for
# why this exists. Wall-clock timeout guards against pathological/hanging documents
# (deeply nested XML, degenerate PDF object graphs); the memory cap guards against
# compression-bomb-style documents (a small compressed file that expands to gigabytes
# when python-docx/pdfminer decompress it - the outer ZIP-upload path already caps
# declared entry sizes, see file_service.MAX_ZIP_TOTAL_BYTES, but that check doesn't
# reach *inside* a single .docx/.pdf, which is itself a compressed container).
PARSE_TIMEOUT_SECONDS = 20.0
PARSE_MEMORY_LIMIT_BYTES = 512 * 1024 * 1024
POOL_SIZE = 2

_ctx = mp.get_context("spawn")


def _worker_loop(task_queue: "mp.Queue", result_queue: "mp.Queue") -> None:
    """Runs in the child process for its whole lifetime, parsing one document per
    iteration - avoids re-importing python-docx/pdfplumber/the app package (multiple
    seconds under `spawn`) on every single upload. A worker that fails to finish a task
    in time is terminated by the parent (see parse_document_isolated) and never reused,
    so this loop never needs its own internal timeout."""
    if sys.platform != "win32":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (PARSE_MEMORY_LIMIT_BYTES, PARSE_MEMORY_LIMIT_BYTES))
    # word_import_service pulls in scipy (via optimal_assignment.py's linear_sum_assignment)
    # for the small attendance-matching matrices it solves - single-threaded BLAS is plenty
    # for that size of problem, but left at its default, OpenBLAS sizes its thread pool off
    # the host's CPU count, not this process's RLIMIT_AS cap above. On a many-core host that
    # thread pool alone can exceed the 512MB cap before any document parsing even starts,
    # surfacing as an opaque PARSE_TIMEOUT_SECONDS timeout instead of a clear OOM.
    import os

    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    from app.services.word_import_service import parse_document

    while True:
        raw_bytes = task_queue.get()
        if raw_bytes is None:
            return
        try:
            result_queue.put(("ok", parse_document(raw_bytes)))
        except BaseException as exc:  # noqa: BLE001 - must never let the child die silently
            result_queue.put(("error", f"{type(exc).__name__}: {exc}"))


class _Worker:
    def __init__(self) -> None:
        self.task_queue: mp.Queue = _ctx.Queue()
        self.result_queue: mp.Queue = _ctx.Queue()
        self.process = _ctx.Process(
            target=_worker_loop, args=(self.task_queue, self.result_queue), daemon=True
        )
        self.process.start()

    def kill(self) -> None:
        self.process.terminate()
        self.process.join(2)
        if self.process.is_alive():
            self.process.kill()
            self.process.join()


_pool: "queue_module.Queue[_Worker]" = queue_module.Queue()
_pool_lock = threading.Lock()
_pool_started = False


def _ensure_pool() -> None:
    global _pool_started
    with _pool_lock:
        if not _pool_started:
            for _ in range(POOL_SIZE):
                _pool.put(_Worker())
            _pool_started = True


def warm_up_pool() -> None:
    """Starts the worker processes early (called from main.py's lifespan) so the first
    real upload after a deploy doesn't pay the cold-start import cost (python-docx/
    pdfplumber/the app package take several seconds to import under `spawn`, see
    parse_document_isolated's docstring) - subsequent calls reuse the already-warm pool."""
    _ensure_pool()


def parse_document_isolated(raw_bytes: bytes) -> "ParsedDocx":
    """Runs parse_document() in an isolated child process from a small warm pool instead
    of directly in the calling (thread-pool-offloaded, see routes/word_import.py) worker.
    Blocks (queue.Queue.get with no timeout) until a worker is free, which caps
    system-wide concurrent parses at POOL_SIZE per uvicorn worker process - the same
    bound a ProcessPoolExecutor would give. Unlike a plain executor, though, a worker that
    doesn't answer within PARSE_TIMEOUT_SECONDS is hard-killed and permanently discarded
    (replaced by a fresh one) rather than left to keep burning CPU/memory in the
    background - asyncio/concurrent.futures can cancel the *future* on a timeout, but that
    never stops the underlying OS process from continuing to run.
    ParsedDocx/ParsedSection/ParsedTable are plain dataclasses of str/date/list, so they
    pickle cleanly across the process boundary."""
    _ensure_pool()
    worker = _pool.get()
    worker.task_queue.put(raw_bytes)
    try:
        status, payload = worker.result_queue.get(timeout=PARSE_TIMEOUT_SECONDS)
    except queue_module.Empty:
        worker.kill()
        _pool.put(_Worker())
        raise ValueError(
            "Datei konnte nicht innerhalb der Zeitgrenze verarbeitet werden "
            "(möglicherweise beschädigt oder ungewöhnlich komplex)"
        )

    _pool.put(worker)
    if status == "error":
        raise ValueError(f"Datei konnte nicht gelesen werden: {payload}")
    return payload
