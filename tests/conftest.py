"""Shared test fixtures: fresh in-memory database per test."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from database import db as db_module
from database.db import get_session, init_engine
from database.models import Batch, Lecture, SourceFile, Subject, Topic


@pytest.fixture()
def fresh_db():
    init_engine("sqlite:///:memory:")
    yield
    # next test re-initialises


@pytest.fixture()
def sample_file(fresh_db) -> int:
    """Create batch->subject->topic->lecture->file; return the file pk."""
    with get_session() as s:
        b = Batch(source_id="b1", name="Test Batch")
        s.add(b); s.flush()
        sub = Subject(source_id="s1", batch_id=b.id, name="Geography")
        s.add(sub); s.flush()
        top = Topic(source_id="t1", subject_id=sub.id, name="Irrigation")
        s.add(top); s.flush()
        lec = Lecture(source_id="l1", topic_id=top.id, name="Lecture 35", number=35)
        s.add(lec); s.flush()
        f = SourceFile(source_id="f1", lecture_id=lec.id,
                       title="Lecture-35 | Test.mp4", file_type="video",
                       file_size=100, original_filename="Test.mp4")
        s.add(f); s.flush()
        return f.id
