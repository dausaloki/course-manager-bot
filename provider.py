"""Abstract CourseProvider interface + provider exceptions.

Every source application is integrated exclusively through this interface.
Implementations MUST talk only to official/authorized APIs and MUST NOT
bypass DRM, encryption, authentication or any access control.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from app_api.models import (
    BatchInfo,
    FileInfo,
    LectureInfo,
    ProviderSession,
    SubjectInfo,
    TopicInfo,
)


class ProviderError(Exception):
    """Base class - message is safe to show to the admin."""


class AuthenticationError(ProviderError):
    """Invalid credentials or rejected login."""


class SessionExpiredError(ProviderError):
    """Stored session/token is no longer valid - user must log in again."""


class ProviderUnavailableError(ProviderError):
    """Source API unreachable / server error / timeout (temporary)."""


class NotAuthorizedError(ProviderError):
    """Account does not have access to the requested resource."""


class ProviderNotConfiguredError(ProviderError):
    """Official API details are missing - see OfficialAppProvider docs."""


class CourseProvider(ABC):
    """Interface every source-application adapter implements."""

    @abstractmethod
    async def login(self, username: str, password: str) -> ProviderSession:
        """Authenticate through the official API. The password is used once
        for this call and never stored anywhere."""

    @abstractmethod
    async def logout(self) -> None:
        """Invalidate the current session (best effort)."""

    def restore(self, session: ProviderSession) -> None:
        """Adopt a previously stored session token (optional override)."""
        self._session = session  # type: ignore[attr-defined]

    @abstractmethod
    async def get_batches(self) -> list[BatchInfo]:
        """Batches the authenticated account is authorized to access."""

    @abstractmethod
    async def get_subjects(self, batch_id: str) -> list[SubjectInfo]: ...

    @abstractmethod
    async def get_topics(self, batch_id: str, subject_id: str) -> list[TopicInfo]: ...

    @abstractmethod
    async def get_lectures(self, batch_id: str, topic_id: str) -> list[LectureInfo]: ...

    @abstractmethod
    async def get_files(self, batch_id: str, lecture_id: str) -> list[FileInfo]: ...

    @abstractmethod
    async def get_file_metadata(self, file_id: str) -> FileInfo: ...

    @abstractmethod
    async def get_download_url(self, file_id: str) -> str:
        """Return an authorized download URL provided by the official API."""
