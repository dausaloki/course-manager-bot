"""Engine/session management + settings helpers.

``init_engine`` may be called with a custom URL (used by the tests with an
in-memory database).  All queries go through the ORM => parameterized SQL.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from config import CONFIG
from database.models import Base, IndexCounter, Setting

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None
_index_lock = threading.Lock()

DEFAULT_SETTINGS: dict[str, str] = {
    "caption_template": "Index: {index}\n\nTitle: {title}\n\nTopic: {topic}\n\nBatch: {batch}",
    "retry_count": "3",
    "upload_concurrency": "1",
    "destination_chat_id": "",       # empty => use CONFIG.chat_id
    "notifications": "on",
    "auto_index": "on",
    "queue_paused": "off",
}


def init_engine(url: str | None = None) -> Engine:
    """(Re)create the engine + session factory and ensure the schema exists."""
    global _engine, _SessionLocal
    url = url or CONFIG.database_url
    kwargs: dict = {"future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url:
            kwargs["poolclass"] = StaticPool
    _engine = create_engine(url, **kwargs)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    Base.metadata.create_all(_engine)
    _seed_defaults()
    return _engine


def _ensure_ready() -> None:
    if _SessionLocal is None:
        init_engine()


@contextmanager
def get_session() -> Iterator[Session]:
    """Transactional session scope - commits on success, rolls back on error."""
    _ensure_ready()
    assert _SessionLocal is not None
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _seed_defaults() -> None:
    assert _SessionLocal is not None
    session = _SessionLocal()
    try:
        for key, value in DEFAULT_SETTINGS.items():
            if session.get(Setting, key) is None:
                session.add(Setting(key=key, value=value))
        if session.get(IndexCounter, 1) is None:
            session.add(IndexCounter(id=1, value=CONFIG.index_start - 1))
        session.commit()
    finally:
        session.close()


# ------------------------------------------------------------- settings
def get_setting(key: str, default: str = "") -> str:
    with get_session() as session:
        row = session.get(Setting, key)
        return row.value if row is not None else default


def set_setting(key: str, value: str) -> None:
    with get_session() as session:
        row = session.get(Setting, key)
        if row is None:
            session.add(Setting(key=key, value=value))
        else:
            row.value = value


# ------------------------------------------------------------- indexing
def allocate_index() -> int:
    """Allocate the next unique upload index.

    Protected by a process-wide lock *and* a DB transaction so concurrent
    uploads can never receive the same number, and the value survives
    restarts because it lives in the ``index_counter`` table.
    """
    with _index_lock:
        with get_session() as session:
            counter = session.execute(
                select(IndexCounter).where(IndexCounter.id == 1).with_for_update()
            ).scalar_one_or_none()
            if counter is None:
                counter = IndexCounter(id=1, value=CONFIG.index_start - 1)
                session.add(counter)
                session.flush()
            counter.value += 1
            return counter.value
