"""Search + upload history queries (always parameterized via the ORM)."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import or_, select

from database.db import get_session
from database.models import (
    Batch,
    Lecture,
    QueueStatus,
    SourceFile,
    Subject,
    TelegramUpload,
    Topic,
)


@dataclass
class UploadRow:
    """Flat, session-independent row for display."""
    index_no: int
    title: str
    batch: str
    subject: str
    topic: str
    lecture: str
    file_type: str
    status: str
    message_id: int | None
    chat_id: str
    uploaded_at: str


def _base_query():
    return (
        select(TelegramUpload, SourceFile, Lecture, Topic, Subject, Batch)
        .join(SourceFile, SourceFile.id == TelegramUpload.source_file_id)
        .join(Lecture, Lecture.id == SourceFile.lecture_id)
        .join(Topic, Topic.id == Lecture.topic_id)
        .join(Subject, Subject.id == Topic.subject_id)
        .join(Batch, Batch.id == Subject.batch_id)
    )


def _to_row(tu: TelegramUpload, f: SourceFile, lec: Lecture, top: Topic,
            sub: Subject, bat: Batch) -> UploadRow:
    return UploadRow(
        index_no=tu.index_no, title=f.title, batch=bat.name, subject=sub.name,
        topic=top.name, lecture=lec.name, file_type=f.file_type, status=tu.status,
        message_id=tu.message_id, chat_id=tu.chat_id,
        uploaded_at=tu.uploaded_at.strftime("%Y-%m-%d %H:%M") if tu.uploaded_at else "",
    )


def search_uploads(query: str, limit: int = 200) -> list[UploadRow]:
    """Search by index, title, batch, subject, topic, lecture, file type or
    Telegram message id."""
    q = query.strip()
    stmt = _base_query()
    conditions = [
        SourceFile.title.ilike(f"%{q}%"),
        Batch.name.ilike(f"%{q}%"),
        Subject.name.ilike(f"%{q}%"),
        Topic.name.ilike(f"%{q}%"),
        Lecture.name.ilike(f"%{q}%"),
        SourceFile.file_type.ilike(q),
    ]
    if q.isdigit():
        num = int(q)
        conditions.append(TelegramUpload.index_no == num)
        conditions.append(TelegramUpload.message_id == num)
    stmt = stmt.where(or_(*conditions)).order_by(TelegramUpload.index_no).limit(limit)
    with get_session() as session:
        return [_to_row(*row) for row in session.execute(stmt).all()]


def upload_history(status_filter: str = "ALL", limit: int = 300) -> list[UploadRow]:
    """History rows, optionally filtered by status.

    'PENDING'/'FAILED' come from the queue (not yet in telegram_uploads),
    so those are synthesized from queue items for a complete picture.
    """
    rows: list[UploadRow] = []
    with get_session() as session:
        if status_filter in ("ALL", "COMPLETED"):
            stmt = _base_query().order_by(TelegramUpload.index_no.desc()).limit(limit)
            rows.extend(_to_row(*r) for r in session.execute(stmt).all())
        if status_filter in ("ALL", "FAILED", "PENDING"):
            from database.models import UploadQueueItem

            wanted = [QueueStatus.FAILED, QueueStatus.PENDING] if status_filter == "ALL" \
                else [status_filter]
            stmt2 = (
                select(UploadQueueItem, SourceFile, Lecture, Topic, Subject, Batch)
                .join(SourceFile, SourceFile.id == UploadQueueItem.source_file_id)
                .join(Lecture, Lecture.id == SourceFile.lecture_id)
                .join(Topic, Topic.id == Lecture.topic_id)
                .join(Subject, Subject.id == Topic.subject_id)
                .join(Batch, Batch.id == Subject.batch_id)
                .where(UploadQueueItem.status.in_(wanted))
                .order_by(UploadQueueItem.id.desc())
                .limit(limit)
            )
            for qi, f, lec, top, sub, bat in session.execute(stmt2).all():
                rows.append(UploadRow(
                    index_no=0, title=f.title, batch=bat.name, subject=sub.name,
                    topic=top.name, lecture=lec.name, file_type=f.file_type,
                    status=qi.status, message_id=None, chat_id="",
                    uploaded_at=qi.updated_at.strftime("%Y-%m-%d %H:%M") if qi.updated_at else "",
                ))
    return rows
