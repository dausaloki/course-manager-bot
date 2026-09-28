"""SQLAlchemy 2.0 ORM models.

SQLite today, PostgreSQL-ready: only portable column types are used and all
relationships are declared with proper foreign keys.
No raw passwords are ever stored - only opaque provider session tokens.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------- statuses
class QueueStatus:
    PENDING = "PENDING"
    UPLOADING = "UPLOADING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    ALL = (PENDING, UPLOADING, COMPLETED, FAILED, CANCELLED)


# ---------------------------------------------------------------- tables
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str] = mapped_column(String(64), default="")
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    sessions: Mapped[list["AppSession"]] = relationship(back_populates="user")


class AppSession(Base):
    """Provider session: only the opaque token is stored, never a password."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    account_label: Mapped[str] = mapped_column(String(190), default="")
    session_token: Mapped[str] = mapped_column(Text, default="")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped["User"] = relationship(back_populates="sessions")


class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[str] = mapped_column(String(190), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(300))
    validity: Mapped[str] = mapped_column(String(100), default="")
    subject_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lecture_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    subjects: Mapped[list["Subject"]] = relationship(back_populates="batch")


class Subject(Base):
    __tablename__ = "subjects"
    __table_args__ = (UniqueConstraint("batch_id", "source_id", name="uq_subject_src"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[str] = mapped_column(String(190), index=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id"), index=True)
    name: Mapped[str] = mapped_column(String(300))

    batch: Mapped["Batch"] = relationship(back_populates="subjects")
    topics: Mapped[list["Topic"]] = relationship(back_populates="subject")


class Topic(Base):
    __tablename__ = "topics"
    __table_args__ = (UniqueConstraint("subject_id", "source_id", name="uq_topic_src"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[str] = mapped_column(String(190), index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), index=True)
    name: Mapped[str] = mapped_column(String(300))

    subject: Mapped["Subject"] = relationship(back_populates="topics")
    lectures: Mapped[list["Lecture"]] = relationship(back_populates="topic")


class Lecture(Base):
    __tablename__ = "lectures"
    __table_args__ = (UniqueConstraint("topic_id", "source_id", name="uq_lecture_src"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[str] = mapped_column(String(190), index=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    topic: Mapped["Topic"] = relationship(back_populates="lectures")
    files: Mapped[list["SourceFile"]] = relationship(back_populates="lecture")


class SourceFile(Base):
    __tablename__ = "source_files"
    __table_args__ = (UniqueConstraint("lecture_id", "source_id", name="uq_file_src"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[str] = mapped_column(String(190), index=True)
    lecture_id: Mapped[int] = mapped_column(ForeignKey("lectures.id"), index=True)
    title: Mapped[str] = mapped_column(String(500))
    file_type: Mapped[str] = mapped_column(String(20), index=True)  # video / pdf / other
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    original_filename: Mapped[str] = mapped_column(String(500), default="")
    source_ref: Mapped[str] = mapped_column(String(500), default="")
    content_hash: Mapped[str] = mapped_column(String(128), default="", index=True)
    published_at: Mapped[str] = mapped_column(String(50), default="")

    lecture: Mapped["Lecture"] = relationship(back_populates="files")
    queue_items: Mapped[list["UploadQueueItem"]] = relationship(back_populates="source_file")
    uploads: Mapped[list["TelegramUpload"]] = relationship(back_populates="source_file")


class UploadQueueItem(Base):
    __tablename__ = "upload_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_file_id: Mapped[int] = mapped_column(ForeignKey("source_files.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default=QueueStatus.PENDING, index=True)
    force: Mapped[bool] = mapped_column(Boolean, default=False)  # re-upload despite duplicate
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    source_file: Mapped["SourceFile"] = relationship(back_populates="queue_items")


class TelegramUpload(Base):
    __tablename__ = "telegram_uploads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    index_no: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    source_file_id: Mapped[int] = mapped_column(ForeignKey("source_files.id"), index=True)
    telegram_file_id: Mapped[str] = mapped_column(String(300), default="")
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    chat_id: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(20), default=QueueStatus.COMPLETED, index=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    source_file: Mapped["SourceFile"] = relationship(back_populates="uploads")


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class LogEntry(Base):
    __tablename__ = "logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    level: Mapped[str] = mapped_column(String(10), default="INFO")
    event: Mapped[str] = mapped_column(String(100), index=True)
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IndexCounter(Base):
    """Single-row table guaranteeing unique, restart-safe sequential indexes."""

    __tablename__ = "index_counter"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    value: Mapped[int] = mapped_column(Integer, default=0)
