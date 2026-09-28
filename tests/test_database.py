"""Database tests: schema, relationships, unique restart-safe indexing."""
from __future__ import annotations

import threading

from sqlalchemy import select

from database.db import allocate_index, get_session, get_setting, init_engine, set_setting
from database.models import Batch, SourceFile, Subject, TelegramUpload


def test_schema_and_relationships(sample_file):
    with get_session() as s:
        f = s.get(SourceFile, sample_file)
        assert f is not None
        lecture = f.lecture
        assert lecture.name == "Lecture 35"
        assert lecture.topic.subject.batch.name == "Test Batch"


def test_settings_roundtrip(fresh_db):
    assert get_setting("retry_count", "") == "3"  # seeded default
    set_setting("retry_count", "5")
    assert get_setting("retry_count") == "5"


def test_index_sequential_and_unique(fresh_db):
    values = [allocate_index() for _ in range(5)]
    assert values == sorted(values)
    assert len(set(values)) == 5
    assert values[1] == values[0] + 1


def test_index_concurrent_no_duplicates(fresh_db):
    results: list[int] = []
    lock = threading.Lock()

    def worker():
        for _ in range(20):
            v = allocate_index()
            with lock:
                results.append(v)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == 100
    assert len(set(results)) == 100, "duplicate indexes allocated!"


def test_index_survives_reconnect(tmp_path):
    url = f"sqlite:///{tmp_path}/persist.db"
    init_engine(url)
    first = allocate_index()
    second = allocate_index()
    # simulate restart
    init_engine(url)
    third = allocate_index()
    assert third == second + 1 > first


def test_upload_record_unique_index(sample_file):
    from services.upload_service import record_upload

    up1 = record_upload(sample_file, "FILEID1", 111, "-100123")
    up2 = record_upload(sample_file, "FILEID2", 112, "-100123")
    assert up1.index_no != up2.index_no
    with get_session() as s:
        rows = s.execute(select(TelegramUpload)).scalars().all()
        assert len(rows) == 2
