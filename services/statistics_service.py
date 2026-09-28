"""Aggregated statistics for the 📊 Statistics screen."""
from __future__ import annotations

from sqlalchemy import func, select

from database.db import get_session
from database.models import (
    Batch,
    Lecture,
    QueueStatus,
    SourceFile,
    Subject,
    TelegramUpload,
    Topic,
    UploadQueueItem,
)


def collect_statistics() -> dict[str, int]:
    with get_session() as session:
        def count(model) -> int:
            return session.execute(select(func.count()).select_from(model)).scalar_one()

        stats = {
            "batches": count(Batch),
            "subjects": count(Subject),
            "topics": count(Topic),
            "lectures": count(Lecture),
            "files": count(SourceFile),
            "videos": session.execute(
                select(func.count()).select_from(SourceFile)
                .where(SourceFile.file_type == "video")).scalar_one(),
            "pdfs": session.execute(
                select(func.count()).select_from(SourceFile)
                .where(SourceFile.file_type == "pdf")).scalar_one(),
            "uploaded": session.execute(
                select(func.count()).select_from(TelegramUpload)
                .where(TelegramUpload.status == QueueStatus.COMPLETED)).scalar_one(),
            "pending": session.execute(
                select(func.count()).select_from(UploadQueueItem)
                .where(UploadQueueItem.status == QueueStatus.PENDING)).scalar_one(),
            "failed": session.execute(
                select(func.count()).select_from(UploadQueueItem)
                .where(UploadQueueItem.status == QueueStatus.FAILED)).scalar_one(),
        }
    return stats
