"""Course service: provider lifecycle + mirroring the authorized course
structure into the local database (so navigation callbacks can use small
integer primary keys and history/search work offline)."""
from __future__ import annotations

from sqlalchemy import select

from app_api import create_provider
from app_api.auth import clear_session, load_session, save_session
from app_api.models import BatchInfo, FileInfo, LectureInfo, SubjectInfo, TopicInfo
from app_api.provider import CourseProvider
from database.db import get_session
from database.models import Batch, Lecture, SourceFile, Subject, Topic
from utils.logger import get_logger, log_event

logger = get_logger(__name__)

# one admin => a tiny registry keyed by telegram user id
_providers: dict[int, CourseProvider] = {}


def get_provider(telegram_id: int) -> CourseProvider:
    """Return (and lazily create) the provider for this admin.

    A stored session token is restored automatically so a bot restart does
    not force a fresh login while the token is still valid.
    """
    provider = _providers.get(telegram_id)
    if provider is None:
        provider = create_provider()
        stored = load_session(telegram_id)
        if stored is not None:
            provider.restore(stored)
        _providers[telegram_id] = provider
    return provider


async def login(telegram_id: int, username: str, password: str) -> str:
    """Login through the provider; persist only the session token."""
    provider = get_provider(telegram_id)
    ps = await provider.login(username, password)
    save_session(telegram_id, ps)
    return ps.account_label


async def logout(telegram_id: int) -> None:
    provider = _providers.pop(telegram_id, None)
    if provider is not None:
        try:
            await provider.logout()
        except Exception as exc:  # best effort
            logger.warning("logout error: %s", exc)
    clear_session(telegram_id)


def is_logged_in(telegram_id: int) -> bool:
    return load_session(telegram_id) is not None


# --------------------------------------------------------------- DB mirror
def upsert_batches(infos: list[BatchInfo]) -> list[Batch]:
    with get_session() as session:
        out: list[Batch] = []
        for info in infos:
            row = session.execute(
                select(Batch).where(Batch.source_id == info.id)
            ).scalar_one_or_none()
            if row is None:
                row = Batch(source_id=info.id, name=info.name)
                session.add(row)
            row.name = info.name or row.name
            row.validity = info.validity or row.validity
            row.subject_count = info.subject_count
            row.lecture_count = info.lecture_count
            session.flush()
            out.append(row)
        log_event("INFO", "batches_retrieved", f"count={len(out)}")
        return out


def upsert_subjects(batch_pk: int, infos: list[SubjectInfo]) -> list[Subject]:
    with get_session() as session:
        out: list[Subject] = []
        for info in infos:
            row = session.execute(
                select(Subject).where(Subject.batch_id == batch_pk,
                                      Subject.source_id == info.id)
            ).scalar_one_or_none()
            if row is None:
                row = Subject(source_id=info.id, batch_id=batch_pk, name=info.name)
                session.add(row)
            row.name = info.name or row.name
            session.flush()
            out.append(row)
        return out


def upsert_topics(subject_pk: int, infos: list[TopicInfo]) -> list[Topic]:
    with get_session() as session:
        out: list[Topic] = []
        for info in infos:
            row = session.execute(
                select(Topic).where(Topic.subject_id == subject_pk,
                                    Topic.source_id == info.id)
            ).scalar_one_or_none()
            if row is None:
                row = Topic(source_id=info.id, subject_id=subject_pk, name=info.name)
                session.add(row)
            row.name = info.name or row.name
            session.flush()
            out.append(row)
        return out


def upsert_lectures(topic_pk: int, infos: list[LectureInfo]) -> list[Lecture]:
    with get_session() as session:
        out: list[Lecture] = []
        for info in infos:
            row = session.execute(
                select(Lecture).where(Lecture.topic_id == topic_pk,
                                      Lecture.source_id == info.id)
            ).scalar_one_or_none()
            if row is None:
                row = Lecture(source_id=info.id, topic_id=topic_pk, name=info.name)
                session.add(row)
            row.name = info.name or row.name
            row.number = info.number
            session.flush()
            out.append(row)
        return out


def upsert_files(lecture_pk: int, infos: list[FileInfo]) -> list[SourceFile]:
    with get_session() as session:
        out: list[SourceFile] = []
        for info in infos:
            row = session.execute(
                select(SourceFile).where(SourceFile.lecture_id == lecture_pk,
                                         SourceFile.source_id == info.id)
            ).scalar_one_or_none()
            if row is None:
                row = SourceFile(source_id=info.id, lecture_id=lecture_pk,
                                 title=info.title, file_type=info.file_type)
                session.add(row)
            row.title = info.title or row.title
            row.file_type = info.file_type or row.file_type
            row.file_size = info.file_size
            row.original_filename = info.original_filename or row.original_filename
            row.source_ref = info.source_ref or row.source_ref
            row.content_hash = info.content_hash or row.content_hash
            row.published_at = info.published_at or row.published_at
            session.flush()
            out.append(row)
        return out


# --------------------------------------------------------------- lookups
def get_batch(pk: int) -> Batch | None:
    with get_session() as s:
        return s.get(Batch, pk)


def get_subject(pk: int) -> Subject | None:
    with get_session() as s:
        return s.get(Subject, pk)


def get_topic(pk: int) -> Topic | None:
    with get_session() as s:
        return s.get(Topic, pk)


def get_lecture(pk: int) -> Lecture | None:
    with get_session() as s:
        return s.get(Lecture, pk)


def get_file(pk: int) -> SourceFile | None:
    with get_session() as s:
        return s.get(SourceFile, pk)


def file_context(pk: int) -> dict[str, str]:
    """Return batch/subject/topic/lecture names for a source file."""
    with get_session() as s:
        f = s.get(SourceFile, pk)
        if f is None:
            return {}
        lec = s.get(Lecture, f.lecture_id)
        top = s.get(Topic, lec.topic_id) if lec else None
        sub = s.get(Subject, top.subject_id) if top else None
        bat = s.get(Batch, sub.batch_id) if sub else None
        return {
            "title": f.title,
            "file_type": f.file_type,
            "lecture": lec.name if lec else "",
            "topic": top.name if top else "",
            "subject": sub.name if sub else "",
            "batch": bat.name if bat else "",
            "date": f.published_at or "",
        }


def files_in_lecture(lecture_pk: int) -> list[SourceFile]:
    with get_session() as s:
        return list(s.execute(
            select(SourceFile).where(SourceFile.lecture_id == lecture_pk)
            .order_by(SourceFile.id)
        ).scalars().all())


def file_pks_in_topic(topic_pk: int) -> list[int]:
    with get_session() as s:
        return list(s.execute(
            select(SourceFile.id)
            .join(Lecture, Lecture.id == SourceFile.lecture_id)
            .where(Lecture.topic_id == topic_pk)
        ).scalars().all())


def file_pks_in_batch(batch_pk: int) -> list[int]:
    with get_session() as s:
        return list(s.execute(
            select(SourceFile.id)
            .join(Lecture, Lecture.id == SourceFile.lecture_id)
            .join(Topic, Topic.id == Lecture.topic_id)
            .join(Subject, Subject.id == Topic.subject_id)
            .where(Subject.batch_id == batch_pk)
        ).scalars().all())
