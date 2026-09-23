from queue import Queue
from unittest.mock import Mock

import pytest

from app.services import isolated_parse as parser


def worker(status="ok", payload="parsed", completed=0):
    result = Mock()
    result.result_queue = Queue()
    result.result_queue.put((status, payload))
    result.completed_tasks = completed
    return result


@pytest.mark.parametrize("completed", [0, parser.MAX_TASKS_PER_WORKER - 1])
def test_recycles_at_limit_without_losing_successful_result(monkeypatch, completed):
    original = worker(completed=completed)
    replacement = worker()
    pool = Queue()
    pool.put(original)
    monkeypatch.setattr(parser, "_pool", pool)
    monkeypatch.setattr(parser, "_ensure_pool", lambda: None)
    monkeypatch.setattr(parser, "_Worker", lambda: replacement)
    assert parser.parse_document_isolated(b"document") == "parsed"
    if completed == parser.MAX_TASKS_PER_WORKER - 1:
        original.kill.assert_called_once()
        assert pool.get_nowait() is replacement
    else:
        original.kill.assert_not_called()
        assert pool.get_nowait() is original


def test_failed_worker_does_not_poison_later_documents(monkeypatch):
    original = worker("error", "XMLSyntaxError: out of memory")
    replacement = worker()
    pool = Queue()
    pool.put(original)
    monkeypatch.setattr(parser, "_pool", pool)
    monkeypatch.setattr(parser, "_ensure_pool", lambda: None)
    monkeypatch.setattr(parser, "_Worker", lambda: replacement)
    with pytest.raises(ValueError, match="XMLSyntaxError"):
        parser.parse_document_isolated(b"first")
    original.kill.assert_called_once()
    assert parser.parse_document_isolated(b"next") == "parsed"


def test_shutdown_kills_workers_and_allows_pool_restart(monkeypatch):
    originals = [worker() for _ in range(parser.POOL_SIZE)]
    pool = Queue()
    for item in originals:
        pool.put(item)
    monkeypatch.setattr(parser, "_pool", pool)
    monkeypatch.setattr(parser, "_pool_started", True)
    factory = Mock(side_effect=lambda: worker())
    monkeypatch.setattr(parser, "_Worker", factory)

    parser.shutdown_pool()
    parser.shutdown_pool()

    for item in originals:
        item.kill.assert_called_once()
    assert pool.empty()
    assert not parser._pool_started

    parser.warm_up_pool()
    assert factory.call_count == parser.POOL_SIZE
    assert pool.qsize() == parser.POOL_SIZE
    assert parser._pool_started
