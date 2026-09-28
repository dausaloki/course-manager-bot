"""Upload bookkeeping: duplicate detection + telegram_uploads records."""
from __future__ import annotations

from sqlalchemy import select

from database.db import allocate_index, get_session
from database.models import QueueStatus, SourceFile, TelegramUpload
from utils.logger import get_logger, log_event

logger = get_logger(__name__)


def find_existing_upload(source_file_pk: int) -> TelegramUpload | None:
    """Return the completed upload for this source file, if any (duplicate
    detection by source file identity; the mirror rows already key on
    source id + lecture + type + hash where available)."""
    with get_session() as session:
        return session.execute(
            select(TelegramUpload)
            .where(TelegramUpload.source_file_id == source_file_pk,
                   TelegramUpload.status == QueueStatus.COMPLETED)
            .order_by(TelegramUpload.id.desc())
        ).scalars().first()


def find_duplicates(source_file_pks: list[int]) -> dict[int, TelegramUpload]:
    """Map of source_file_pk -> existing completed upload."""
    if not source_file_pks:
        return {}
    with get_session() as session:
        rows = session.execute(
            select(TelegramUpload)
            .where(TelegramUpload.source_file_id.in_(source_file_pks),
                   TelegramUpload.status == QueueStatus.COMPLETED)
            .order_by(TelegramUpload.id)
        ).scalars().all()
        return {r.source_file_id: r for r in rows}


def find_reusable_file_id(source_file_pk: int) -> str:
    """If Telegram already hosts this exact file, reuse its file_id instead
    of re-uploading the bytes."""
    existing = find_existing_upload(source_file_pk)
    if existing and existing.telegram_file_id:
        return existing.telegram_file_id
    # also match by content hash across file rows
    with get_session() as session:
        f = session.get(SourceFile, source_file_pk)
        if f is None or not f.content_hash:
            return ""
        twin = session.execute(
            select(TelegramUpload)
            .join(SourceFile, SourceFile.id == TelegramUpload.source_file_id)
            .where(SourceFile.content_hash == f.content_hash,
                   TelegramUpload.status == QueueStatus.COMPLETED,
                   TelegramUpload.telegram_file_id != "")
            .order_by(TelegramUpload.id.desc())
        ).scalars().first()
        return twin.telegram_file_id if twin else ""


def record_upload(source_file_pk: int, telegram_file_id: str, message_id: int | None,
                  chat_id: str) -> TelegramUpload:
    """Allocate a unique index and persist the completed upload atomically."""
    index_no = allocate_index()
    with get_session() as session:
        upload = TelegramUpload(
            index_no=index_no,
            source_file_id=source_file_pk,
            telegram_file_id=telegram_file_id or "",
            message_id=message_id,
            chat_id=str(chat_id),
            status=QueueStatus.COMPLETED,
        )
        session.add(upload)
        session.flush()
        log_event("INFO", "upload_completed",
                  f"index={index_no} source_file={source_file_pk} msg={message_id}")
        return upload
