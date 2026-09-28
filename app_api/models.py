"""Plain data transfer objects returned by every CourseProvider.

Only metadata actually supplied by the source is filled in - nothing is
invented; unknown values stay ``None`` / empty string.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ProviderSession:
    token: str
    account_label: str = ""
    expires_at: datetime | None = None


@dataclass
class BatchInfo:
    id: str
    name: str
    validity: str = ""
    subject_count: int | None = None
    lecture_count: int | None = None


@dataclass
class SubjectInfo:
    id: str
    batch_id: str
    name: str


@dataclass
class TopicInfo:
    id: str
    subject_id: str
    name: str


@dataclass
class LectureInfo:
    id: str
    topic_id: str
    name: str
    number: int | None = None


@dataclass
class FileInfo:
    id: str
    lecture_id: str
    title: str
    file_type: str  # "video" | "pdf" | "other"
    file_size: int | None = None
    original_filename: str = ""
    source_ref: str = ""
    content_hash: str = ""
    published_at: str = ""
    extra: dict = field(default_factory=dict)
