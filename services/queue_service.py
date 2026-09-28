"""Persistent upload queue - survives restarts because every state change
is committed to the ``upload_queue`` table immediately."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update

from database.db import get_session, get_setting, set_setting
from database.models import QueueStatus, SourceFile, UploadQueueItem
from utils.logger import get_logger, log_event

logger = get_logger(__name__)


def enqueue(source_file_pks: list[int], force: bool = False) -> int:
    """Add files to the queue; files already PENDING/UPLOADING are skipped
    so the queue never contains accidental duplicates."""
    if not source_file_pks:
        return 0
    added = 0
    with get_session() as session:
        active = set(session.execute(
            select(UploadQueueItem.source_file_id).where(
                UploadQueueItem.source_file_id.in_(source_file_pks),
                UploadQueueItem.status.in_([QueueStatus.PENDING, QueueStatus.UPLOADING]),
            )
        ).scalars().all())
        for pk in source_file_pks:
            if pk in active:
                continue
            session.add(UploadQueueItem(source_file_id=pk, force=force,
                                        status=QueueStatus.PENDING))
            added += 1
    log_event("INFO", "upload_started", f"enqueued={added} force={force}")
    return added


def claim_next() -> UploadQueueItem | None:
    """Atomically claim the next due PENDING item (mark it UPLOADING)."""
    now = datetime.now(timezone.utc)
    with get_session() as session:
        item = session.execute(
            select(UploadQueueItem)
            .where(UploadQueueItem.status == QueueStatus.PENDING)
            .order_by(UploadQueueItem.id)
            .with_for_update(skip_locked=True)
        ).scalars().first()
        if item is None:
            return None
        if item.next_attempt_at is not None:
            due = item.next_attempt_at if item.next_attempt_at.tzinfo else \
                item.next_attempt_at.replace(tzinfo=timezone.utc)
            if due > now:
                return None  # backoff window still open
        item.status = QueueStatus.UPLOADING
        session.flush()
        return item


def mark_completed(item_id: int) -> None:
    _set_status(item_id, QueueStatus.COMPLETED, error="")


def mark_failed(item_id: int, error: str, permanent: bool, max_retries: int,
                backoff_base: float = 5.0) -> str:
    """Handle a failure: schedule a retry with exponential backoff for
    temporary errors, or mark FAILED for permanent / exhausted ones.
    Returns the resulting status."""
    with get_session() as session:
        item = session.get(UploadQueueItem, item_id)
        if item is None:
            return QueueStatus.FAILED
        item.attempts += 1
        item.last_error = error[:1000]
        if permanent or item.attempts > max_retries:
            item.status = QueueStatus.FAILED
            log_event("ERROR", "upload_failed", f"queue_item={item_id} error={error[:200]}")
            return QueueStatus.FAILED
        delay = backoff_base * (2 ** (item.attempts - 1))
        item.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
        item.status = QueueStatus.PENDING
        log_event("WARNING", "upload_retry",
                  f"queue_item={item_id} attempt={item.attempts} delay={delay:.0f}s")
        return QueueStatus.PENDING


def _set_status(item_id: int, status: str, error: str | None = None) -> None:
    with get_session() as session:
        item = session.get(UploadQueueItem, item_id)
        if item is not None:
            item.status = status
            if error is not None:
                item.last_error = error


def cancel_pending() -> int:
    """Cancel all pending items (completed uploads are never touched)."""
    with get_session() as session:
        result = session.execute(
            update(UploadQueueItem)
            .where(UploadQueueItem.status == QueueStatus.PENDING)
            .values(status=QueueStatus.CANCELLED)
        )
        count = result.rowcount or 0
    log_event("INFO", "queue_cancelled", f"count={count}")
    return count


def retry_failed() -> int:
    """Requeue all FAILED items with a fresh attempt counter."""
    with get_session() as session:
        result = session.execute(
            update(UploadQueueItem)
            .where(UploadQueueItem.status == QueueStatus.FAILED)
            .values(status=QueueStatus.PENDING, attempts=0,
                    next_attempt_at=None, last_error="")
        )
        count = result.rowcount or 0
    log_event("INFO", "retry_failed", f"count={count}")
    return count


def queue_counts() -> dict[str, int]:
    with get_session() as session:
        rows = session.execute(
            select(UploadQueueItem.status, func.count(UploadQueueItem.id))
            .group_by(UploadQueueItem.status)
        ).all()
    counts = {status: 0 for status in QueueStatus.ALL}
    for status, n in rows:
        counts[status] = n
    counts["TOTAL"] = sum(counts[s] for s in QueueStatus.ALL)
    return counts


def pending_exists() -> bool:
    with get_session() as session:
        return session.execute(
            select(UploadQueueItem.id)
            .where(UploadQueueItem.status == QueueStatus.PENDING).limit(1)
        ).scalar_one_or_none() is not None


def is_paused() -> bool:
    return get_setting("queue_paused", "off") == "on"


def set_paused(paused: bool) -> None:
    set_setting("queue_paused", "on" if paused else "off")
    log_event("INFO", "queue_paused" if paused else "queue_resumed", "")


def item_file(item_id: int) -> SourceFile | None:
    with get_session() as session:
        item = session.get(UploadQueueItem, item_id)
        if item is None:
            return None
        return session.get(SourceFile, item.source_file_id)
