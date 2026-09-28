"""End-to-end simulated flow (requirement H of the master prompt):

start -> login -> batch -> subject -> topic -> lecture -> select video+pdf
-> indexes -> queue -> worker processes -> file_id/message_id stored ->
duplicate detection -> RESTART simulation -> state verified intact.

Uses a real on-disk SQLite file so the restart simulation is genuine.
Telegram is mocked; TEST_MODE keeps uploads simulated either way.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import func, select

from database.db import allocate_index, get_session, init_engine
from database.migrations import init_db, recover_interrupted_uploads
from database.models import QueueStatus, TelegramUpload, UploadQueueItem
from services import course_service, queue_service, upload_service


async def _wait_queue_drain(timeout: float = 20.0) -> None:
    waited = 0.0
    while waited < timeout:
        counts = queue_service.queue_counts()
        if counts["PENDING"] == 0 and counts["UPLOADING"] == 0:
            return
        await asyncio.sleep(0.3)
        waited += 0.3
    raise AssertionError(f"queue did not drain: {queue_service.queue_counts()}")


def test_complete_end_to_end_flow_with_restart(tmp_path):
    db_url = f"sqlite:///{tmp_path}/e2e.db"
    init_db(db_url)  # 1. start application (db layer)

    async def flow() -> list[int]:
        # 2. simulate admin login
        account = await course_service.login(111, "admin-e2e", "test")
        assert account == "admin-e2e"
        assert course_service.is_logged_in(111)
        p = course_service.get_provider(111)

        # 3-6. batch -> subject -> topic -> lecture
        batch = course_service.upsert_batches(await p.get_batches())[0]
        subject = course_service.upsert_subjects(
            batch.id, await p.get_subjects(batch.source_id))[0]
        topic = course_service.upsert_topics(
            subject.id, await p.get_topics(batch.source_id, subject.source_id))[0]
        lecture = course_service.upsert_lectures(
            topic.id, await p.get_lectures(batch.source_id, topic.source_id))[0]
        files = course_service.upsert_files(
            lecture.id, await p.get_files(batch.source_id, lecture.source_id))

        # 7-8. select the video AND the pdf
        video = next(f for f in files if f.file_type == "video")
        pdf = next(f for f in files if f.file_type == "pdf")
        selected = [video.id, pdf.id]

        # 10. add both to the queue (no duplicates yet)
        assert upload_service.find_duplicates(selected) == {}
        assert queue_service.enqueue(selected) == 2

        # 11-12. process the queue with a mocked Telegram bot (simulated upload)
        from telegram_bot.uploader import UploadWorker

        bot = MagicMock()
        bot.send_message = AsyncMock()
        worker = UploadWorker(bot, 111)
        worker.ensure_running()
        await _wait_queue_drain()
        await worker.shutdown()
        return selected

    selected = asyncio.run(flow())

    # 13-14. verify Telegram file_id / message_id / index stored in database
    with get_session() as s:
        uploads = s.execute(
            select(TelegramUpload).order_by(TelegramUpload.index_no)
        ).scalars().all()
        assert len(uploads) == 2
        indexes = [u.index_no for u in uploads]
        assert indexes == sorted(set(indexes)), "9. indexes unique & sequential"
        for u in uploads:
            assert u.telegram_file_id.startswith("TEST-FILE-")
            assert u.message_id is not None
            assert u.status == QueueStatus.COMPLETED

    counts = queue_service.queue_counts()
    assert counts["COMPLETED"] == 2 and counts["FAILED"] == 0

    # 15. duplicate detection now flags both files
    dups = upload_service.find_duplicates(selected)
    assert set(dups) == set(selected)
    assert upload_service.find_reusable_file_id(selected[0]) != ""

    # 16. RESTART simulation: leave one item stuck in UPLOADING, reconnect
    queue_service.enqueue([selected[0]], force=True)
    stuck = queue_service.claim_next()
    assert stuck is not None  # now UPLOADING when the "crash" happens

    init_engine(db_url)                       # simulate process restart
    recovered = recover_interrupted_uploads() # startup recovery
    assert recovered == 1

    # 17. verify queue/database state after restart
    with get_session() as s:
        item = s.get(UploadQueueItem, stuck.id)
        assert item.status == QueueStatus.PENDING  # recovered, not lost
        n_uploads = s.execute(
            select(func.count()).select_from(TelegramUpload)).scalar_one()
        assert n_uploads == 2  # completed uploads never lost
    next_index = allocate_index()
    assert next_index == 3  # counter survived the restart, no duplicate index
