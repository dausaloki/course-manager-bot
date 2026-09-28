"""TestModeProvider - a fully simulated source application.

Lets you exercise every feature (login, navigation, selection, queue,
indexing, duplicate detection, history, search, statistics) without any
real API and without uploading real files.
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone

from app_api.models import (
    BatchInfo,
    FileInfo,
    LectureInfo,
    ProviderSession,
    SubjectInfo,
    TopicInfo,
)
from app_api.provider import (
    AuthenticationError,
    CourseProvider,
    SessionExpiredError,
)
from utils.logger import get_logger

logger = get_logger(__name__)

# ------------------------------------------------------------------ sample data
_BATCHES = [
    ("b1", "सम्पूर्ण राजस्थान GK - Complete Online Batch", "Valid till 31-12-2026"),
    ("b2", "Rajasthan Geography Special", "Valid till 30-06-2026"),
    ("b3", "Rajasthan History Crash Course", "Valid till 31-03-2026"),
]

_SUBJECTS = {
    "b1": [("s1", "Geography"), ("s2", "History"), ("s3", "Polity")],
    "b2": [("s4", "Physical Geography"), ("s5", "Water Resources")],
    "b3": [("s6", "Ancient Rajasthan"), ("s7", "Modern Rajasthan")],
}

_TOPICS = {
    "s1": [("t1", "Rajasthan Irrigation"), ("t2", "Rivers of Rajasthan")],
    "s2": [("t3", "Rajput Dynasties")],
    "s3": [("t4", "Panchayati Raj")],
    "s4": [("t5", "Desert Landforms")],
    "s5": [("t6", "Canal Systems")],
    "s6": [("t7", "Kalibangan Civilization")],
    "s7": [("t8", "1857 in Rajasthan")],
}


def _build_lectures() -> dict[str, list[tuple[str, str, int]]]:
    lectures: dict[str, list[tuple[str, str, int]]] = {}
    counter = 30
    for topic_ids in _TOPICS.values():
        for tid, tname in topic_ids:
            lectures[tid] = []
            for i in range(1, 4):
                counter += 1
                lectures[tid].append((f"lec{counter}", f"Lecture {counter} | {tname}", counter))
    return lectures


_LECTURES = _build_lectures()


def _build_files() -> dict[str, list[FileInfo]]:
    files: dict[str, list[FileInfo]] = {}
    for lec_list in _LECTURES.values():
        for lec_id, lec_name, num in lec_list:
            base = lec_name.split("|", 1)[1].strip() if "|" in lec_name else lec_name
            video_title = f"Lecture-{num} | राजस्थान : {base} नमस्ते.mp4"
            pdf_title = f"Lecture-{num} | राजस्थान : {base} नमस्ते.pdf"
            files[lec_id] = [
                FileInfo(
                    id=f"{lec_id}-v", lecture_id=lec_id, title=video_title,
                    file_type="video", file_size=350_000_000 + num * 1_000_000,
                    original_filename=video_title,
                    source_ref=f"test://video/{lec_id}",
                    content_hash=hashlib.sha256(f"video-{lec_id}".encode()).hexdigest(),
                    published_at="2026-01-15",
                ),
                FileInfo(
                    id=f"{lec_id}-p", lecture_id=lec_id, title=pdf_title,
                    file_type="pdf", file_size=2_000_000 + num * 10_000,
                    original_filename=pdf_title,
                    source_ref=f"test://pdf/{lec_id}",
                    content_hash=hashlib.sha256(f"pdf-{lec_id}".encode()).hexdigest(),
                    published_at="2026-01-15",
                ),
            ]
    return files


_FILES = _build_files()


class TestModeProvider(CourseProvider):
    """Simulated provider. Any username with password 'test' (or any
    non-empty password) logs in successfully; password 'wrong' fails -
    handy for testing the error path."""

    __test__ = False  # not a pytest test class despite the name

    def __init__(self) -> None:
        self._session: ProviderSession | None = None

    def _check(self) -> None:
        if self._session is None:
            raise SessionExpiredError("Not logged in (test mode). Use 🔐 Login.")

    async def login(self, username: str, password: str) -> ProviderSession:
        await asyncio.sleep(0.3)  # simulate network
        if password.strip().lower() == "wrong":
            raise AuthenticationError("Invalid credentials (simulated).")
        self._session = ProviderSession(
            token="TEST-TOKEN-" + hashlib.sha256(username.encode()).hexdigest()[:16],
            account_label=username,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        logger.info("[TEST MODE] login simulated for '%s'", username)
        return self._session

    async def logout(self) -> None:
        self._session = None

    def restore(self, session: ProviderSession) -> None:
        self._session = session

    async def get_batches(self) -> list[BatchInfo]:
        self._check()
        await asyncio.sleep(0.1)
        out = []
        for bid, name, validity in _BATCHES:
            subj = _SUBJECTS.get(bid, [])
            lec_count = sum(
                len(_LECTURES.get(tid, []))
                for sid, _ in subj
                for tid, _ in _TOPICS.get(sid, [])
            )
            out.append(BatchInfo(id=bid, name=name, validity=validity,
                                 subject_count=len(subj), lecture_count=lec_count))
        return out

    async def get_subjects(self, batch_id: str) -> list[SubjectInfo]:
        self._check()
        await asyncio.sleep(0.05)
        return [SubjectInfo(id=sid, batch_id=batch_id, name=name)
                for sid, name in _SUBJECTS.get(batch_id, [])]

    async def get_topics(self, batch_id: str, subject_id: str) -> list[TopicInfo]:
        self._check()
        await asyncio.sleep(0.05)
        return [TopicInfo(id=tid, subject_id=subject_id, name=name)
                for tid, name in _TOPICS.get(subject_id, [])]

    async def get_lectures(self, batch_id: str, topic_id: str) -> list[LectureInfo]:
        self._check()
        await asyncio.sleep(0.05)
        return [LectureInfo(id=lid, topic_id=topic_id, name=name, number=num)
                for lid, name, num in _LECTURES.get(topic_id, [])]

    async def get_files(self, batch_id: str, lecture_id: str) -> list[FileInfo]:
        self._check()
        await asyncio.sleep(0.05)
        return list(_FILES.get(lecture_id, []))

    async def get_file_metadata(self, file_id: str) -> FileInfo:
        self._check()
        for file_list in _FILES.values():
            for f in file_list:
                if f.id == file_id:
                    return f
        raise SessionExpiredError(f"Unknown test file id {file_id}")

    async def get_download_url(self, file_id: str) -> str:
        self._check()
        return f"test://download/{file_id}"
