"""CourseProvider interface, login/session handling, course navigation
mirror and file selection helpers."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app_api.auth import clear_session, load_session, save_session
from app_api.courses import TestModeProvider
from app_api.models import ProviderSession
from app_api.official_provider import OfficialAppProvider
from app_api.provider import (
    AuthenticationError,
    ProviderNotConfiguredError,
    SessionExpiredError,
)
from services import course_service


# --------------------------------------------------------- provider interface
def test_provider_full_interface():
    async def flow():
        p = TestModeProvider()
        ps = await p.login("user1", "goodpass")
        assert ps.token and ps.account_label == "user1"

        batches = await p.get_batches()
        assert len(batches) == 3
        assert batches[0].validity  # metadata only when provided

        subjects = await p.get_subjects(batches[0].id)
        topics = await p.get_topics(batches[0].id, subjects[0].id)
        lectures = await p.get_lectures(batches[0].id, topics[0].id)
        files = await p.get_files(batches[0].id, lectures[0].id)
        assert {f.file_type for f in files} == {"video", "pdf"}

        meta = await p.get_file_metadata(files[0].id)
        assert meta.title == files[0].title

        url = await p.get_download_url(files[0].id)
        assert url.startswith("test://download/")

        await p.logout()
        with pytest.raises(SessionExpiredError):
            await p.get_batches()

    asyncio.run(flow())


def test_invalid_login_rejected():
    async def flow():
        p = TestModeProvider()
        with pytest.raises(AuthenticationError):
            await p.login("user", "wrong")

    asyncio.run(flow())


def test_calls_require_login():
    async def flow():
        p = TestModeProvider()
        with pytest.raises(SessionExpiredError):
            await p.get_batches()

    asyncio.run(flow())


def test_official_provider_never_guesses_endpoints():
    async def flow():
        p = OfficialAppProvider()
        with pytest.raises(ProviderNotConfiguredError) as exc:
            await p.login("u", "p")
        msg = str(exc.value)
        assert "official" in msg.lower()
        assert "ENDPOINTS" in msg or "FIELD_MAP" in msg
        with pytest.raises(ProviderNotConfiguredError):
            await p.get_batches()

    asyncio.run(flow())


# --------------------------------------------------------- session handling
def test_session_persistence_roundtrip(fresh_db):
    ps = ProviderSession(token="TOK-123", account_label="acc",
                         expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    save_session(777, ps)
    loaded = load_session(777)
    assert loaded is not None
    assert loaded.token == "TOK-123" and loaded.account_label == "acc"
    clear_session(777)
    assert load_session(777) is None


def test_expired_session_not_returned(fresh_db):
    ps = ProviderSession(token="OLD", account_label="acc",
                         expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    save_session(778, ps)
    assert load_session(778) is None  # expired -> treated as logged out


def test_no_password_ever_stored(fresh_db):
    """The sessions table has no password column and tokens are opaque."""
    from database.models import AppSession

    cols = {c.name for c in AppSession.__table__.columns}
    assert "password" not in cols
    ps = ProviderSession(token="OPAQUE", account_label="user")
    save_session(779, ps)
    loaded = load_session(779)
    assert loaded.token == "OPAQUE"  # only the token round-trips


# --------------------------------------------------------- navigation mirror
def test_course_navigation_and_selection_helpers(fresh_db):
    async def flow():
        p = TestModeProvider()
        await p.login("nav", "ok")
        batches = course_service.upsert_batches(await p.get_batches())
        b = batches[0]
        subjects = course_service.upsert_subjects(b.id, await p.get_subjects(b.source_id))
        s = subjects[0]
        topics = course_service.upsert_topics(s.id, await p.get_topics(b.source_id, s.source_id))
        t = topics[0]
        lectures = course_service.upsert_lectures(t.id, await p.get_lectures(b.source_id, t.source_id))
        for lec in lectures:
            course_service.upsert_files(
                lec.id, await p.get_files(b.source_id, lec.source_id))

        # selection helpers: lecture / topic / batch scopes
        in_lecture = course_service.files_in_lecture(lectures[0].id)
        assert len(in_lecture) == 2  # 1 video + 1 pdf
        in_topic = course_service.file_pks_in_topic(t.id)
        assert len(in_topic) == len(lectures) * 2
        in_batch = course_service.file_pks_in_batch(b.id)
        assert set(in_topic) <= set(in_batch)

        # upsert is idempotent -> no duplicate mirror rows
        again = course_service.upsert_files(
            lectures[0].id, await p.get_files(b.source_id, lectures[0].source_id))
        assert [f.id for f in again] == [f.id for f in in_lecture]

        # metadata context for the caption
        ctx = course_service.file_context(in_lecture[0].id)
        assert ctx["batch"] == b.name and ctx["topic"] == t.name
        assert ctx["file_type"] in ("video", "pdf")

    asyncio.run(flow())
