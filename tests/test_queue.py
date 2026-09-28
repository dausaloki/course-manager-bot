"""Queue tests: enqueue, dedupe, state machine, retry, crash recovery."""
from __future__ import annotations

from sqlalchemy import select

from database.db import get_session
from database.models import QueueStatus, UploadQueueItem
from database.migrations import recover_interrupted_uploads
from services import queue_service


def test_enqueue_and_claim(sample_file):
    added = queue_service.enqueue([sample_file])
    assert added == 1
    # duplicate enqueue is refused while PENDING
    assert queue_service.enqueue([sample_file]) == 0

    item = queue_service.claim_next()
    assert item is not None
    assert item.source_file_id == sample_file
    with get_session() as s:
        row = s.get(UploadQueueItem, item.id)
        assert row.status == QueueStatus.UPLOADING

    queue_service.mark_completed(item.id)
    with get_session() as s:
        assert s.get(UploadQueueItem, item.id).status == QueueStatus.COMPLETED


def test_retry_backoff_then_fail(sample_file):
    queue_service.enqueue([sample_file])
    item = queue_service.claim_next()

    # temporary failure -> back to PENDING with backoff
    status = queue_service.mark_failed(item.id, "timeout", permanent=False,
                                       max_retries=2, backoff_base=0.0)
    assert status == QueueStatus.PENDING
    with get_session() as s:
        row = s.get(UploadQueueItem, item.id)
        assert row.attempts == 1
        assert row.status == QueueStatus.PENDING

    # exhaust retries
    item2 = queue_service.claim_next()
    assert item2 is not None
    queue_service.mark_failed(item2.id, "timeout", permanent=False,
                              max_retries=2, backoff_base=0.0)
    item3 = queue_service.claim_next()
    status = queue_service.mark_failed(item3.id, "timeout", permanent=False,
                                       max_retries=2, backoff_base=0.0)
    assert status == QueueStatus.FAILED


def test_permanent_error_fails_immediately(sample_file):
    queue_service.enqueue([sample_file])
    item = queue_service.claim_next()
    status = queue_service.mark_failed(item.id, "403", permanent=True, max_retries=5)
    assert status == QueueStatus.FAILED


def test_retry_failed_requeues(sample_file):
    queue_service.enqueue([sample_file])
    item = queue_service.claim_next()
    queue_service.mark_failed(item.id, "x", permanent=True, max_retries=0)
    assert queue_service.retry_failed() == 1
    with get_session() as s:
        row = s.get(UploadQueueItem, item.id)
        assert row.status == QueueStatus.PENDING
        assert row.attempts == 0


def test_cancel_pending_keeps_completed(sample_file):
    queue_service.enqueue([sample_file])
    item = queue_service.claim_next()
    queue_service.mark_completed(item.id)
    queue_service.enqueue([sample_file])  # allowed again after completion
    assert queue_service.cancel_pending() == 1
    counts = queue_service.queue_counts()
    assert counts["COMPLETED"] == 1
    assert counts["CANCELLED"] == 1


def test_crash_recovery(sample_file):
    queue_service.enqueue([sample_file])
    item = queue_service.claim_next()          # stuck in UPLOADING = crash
    assert recover_interrupted_uploads() == 1  # restart recovery
    with get_session() as s:
        row = s.get(UploadQueueItem, item.id)
        assert row.status == QueueStatus.PENDING
    # completed items are never touched
    item = queue_service.claim_next()
    queue_service.mark_completed(item.id)
    assert recover_interrupted_uploads() == 0


def test_pause_resume(fresh_db):
    assert queue_service.is_paused() is False
    queue_service.set_paused(True)
    assert queue_service.is_paused() is True
    queue_service.set_paused(False)
    assert queue_service.is_paused() is False


def test_duplicate_detection(sample_file):
    from services.upload_service import find_duplicates, find_existing_upload, record_upload

    assert find_existing_upload(sample_file) is None
    record_upload(sample_file, "FID", 999, "-1001")
    existing = find_existing_upload(sample_file)
    assert existing is not None and existing.telegram_file_id == "FID"
    dups = find_duplicates([sample_file, 424242])
    assert sample_file in dups and 424242 not in dups
