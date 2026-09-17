"""Unit tests for worker.py's _process_job loop body - all collaborators (fetch_files,
score_face_quality, write_face_quality_scores_batch, finish_job) are monkeypatched, so
these don't need a database or the real YuNet model."""

from app import worker


def test_process_job_marks_an_unreadable_file_as_analyzed_with_no_score(monkeypatch, tmp_path):
    """Regression for the bug fixed alongside face_analyzed_at: a file missing from disk
    used to be silently skipped (never marked analyzed), so it got retried by every future
    off-peak run forever. It must now be written back with score=None instead."""
    monkeypatch.setattr(worker, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(worker, "fetch_files", lambda engine, ids: [{"id": 1, "storage_path": "does-not-exist.png", "mime_type": "image/png"}])

    written: list[list[tuple[int, float | None]]] = []
    monkeypatch.setattr(worker, "write_face_quality_scores_batch", lambda engine, results: written.append(results))

    finished: list[tuple[str, str]] = []
    monkeypatch.setattr(worker, "finish_job", lambda engine, job_id, *, status, error=None: finished.append((job_id, status)))

    worker._process_job(engine=None, detector=None, job={"id": "job-1", "tenant_id": 1, "stored_file_ids": [1]})

    assert written == [[(1, None)]]
    assert finished == [("job-1", "done")]


def test_process_job_scores_a_readable_file_and_marks_it_done(monkeypatch, tmp_path):
    image_path = tmp_path / "photo.png"
    image_path.write_bytes(b"fake-image-bytes")
    monkeypatch.setattr(worker, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(worker, "fetch_files", lambda engine, ids: [{"id": 7, "storage_path": "photo.png", "mime_type": "image/png"}])
    monkeypatch.setattr(worker, "score_face_quality", lambda detector, image_bytes: 8.25)

    written: list[list[tuple[int, float | None]]] = []
    monkeypatch.setattr(worker, "write_face_quality_scores_batch", lambda engine, results: written.append(results))

    finished: list[tuple[str, str]] = []
    monkeypatch.setattr(worker, "finish_job", lambda engine, job_id, *, status, error=None: finished.append((job_id, status)))

    worker._process_job(engine=None, detector=None, job={"id": "job-2", "tenant_id": 1, "stored_file_ids": [7]})

    assert written == [[(7, 8.25)]]
    assert finished == [("job-2", "done")]


def test_process_job_handles_a_mix_of_readable_and_missing_files(monkeypatch, tmp_path):
    """Regression coverage for the batched write (audit fix, 2026-09-17): both files in
    the job must land in the SAME batch call, not two separate ones - that's the whole
    point of batching (previously one connection-checkout+BEGIN/COMMIT cycle per file)."""
    (tmp_path / "ok.png").write_bytes(b"fake-image-bytes")
    monkeypatch.setattr(worker, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(
        worker,
        "fetch_files",
        lambda engine, ids: [
            {"id": 1, "storage_path": "ok.png", "mime_type": "image/png"},
            {"id": 2, "storage_path": "missing.png", "mime_type": "image/png"},
        ],
    )
    monkeypatch.setattr(worker, "score_face_quality", lambda detector, image_bytes: 5.0)

    written: list[list[tuple[int, float | None]]] = []
    monkeypatch.setattr(worker, "write_face_quality_scores_batch", lambda engine, results: written.append(results))
    monkeypatch.setattr(worker, "finish_job", lambda engine, job_id, *, status, error=None: None)

    worker._process_job(engine=None, detector=None, job={"id": "job-3", "tenant_id": 1, "stored_file_ids": [1, 2]})

    assert written == [[(1, 5.0), (2, None)]]
