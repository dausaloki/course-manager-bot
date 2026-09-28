"""Database initialisation / lightweight migrations.

``init_db`` is idempotent: it creates missing tables, seeds default settings
and performs crash recovery (any item stuck in UPLOADING when the process
died is returned to PENDING so no completed upload is ever lost and no
pending one is forgotten).
"""
from __future__ import annotations

from sqlalchemy import select, update

from database.db import get_session, init_engine
from database.models import QueueStatus, UploadQueueItem
from utils.logger import get_logger

logger = get_logger(__name__)


def init_db(url: str | None = None) -> None:
    """Create schema, seed defaults, recover interrupted queue items."""
    init_engine(url)
    recovered = recover_interrupted_uploads()
    if recovered:
        logger.info("Recovered %d interrupted upload(s) back to PENDING", recovered)
    logger.info("Database initialised")


def recover_interrupted_uploads() -> int:
    """Reset items stuck in UPLOADING (process crash) back to PENDING."""
    with get_session() as session:
        stuck = session.execute(
            select(UploadQueueItem.id).where(UploadQueueItem.status == QueueStatus.UPLOADING)
        ).scalars().all()
        if stuck:
            session.execute(
                update(UploadQueueItem)
                .where(UploadQueueItem.id.in_(stuck))
                .values(status=QueueStatus.PENDING, last_error="recovered after restart")
            )
        return len(stuck)
