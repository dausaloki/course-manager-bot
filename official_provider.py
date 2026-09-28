"""OfficialAppProvider - adapter for YOUR application's OFFICIAL API.

============================  READ THIS FIRST  ============================
This adapter deliberately ships WITHOUT endpoints.  Inventing or guessing
another application's private API would be unreliable and could amount to
circumventing its access controls - which this project never does.

To activate real integration you must supply, from the vendor's OFFICIAL
API documentation (or an API access agreement):

  1. Base URL                -> .env  APP_API_BASE_URL
  2. Auth mechanism          -> ENDPOINTS["login"] + AUTH_STYLE
       - login path, HTTP method, request body fields
       - token type (Bearer / cookie / custom header) and expiry field
  3. Resource endpoints      -> ENDPOINTS["batches" | "subjects" |
                                 "topics" | "lectures" | "files" |
                                 "file_meta" | "download_url"]
       - path templates, e.g.  "/v1/batches/{batch_id}/subjects"
  4. Response field names    -> FIELD_MAP  (which JSON keys hold id, name,
       title, file url, size, type, date ...)
  5. Rate limits / required headers (client id, api key, user agent)

Fill ENDPOINTS + FIELD_MAP below.  Every method already contains the full
HTTP/error/retry plumbing, so once the configuration is complete the whole
bot works end-to-end without further code changes.

Until then every call raises ProviderNotConfiguredError with a precise
explanation - the adapter STOPS instead of guessing.
===========================================================================
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

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
    NotAuthorizedError,
    ProviderNotConfiguredError,
    ProviderUnavailableError,
    SessionExpiredError,
)
from config import CONFIG
from utils.logger import get_logger

logger = get_logger(__name__)

# --------------------------------------------------------------------------
# CONFIGURATION POINT 1: endpoint paths from the OFFICIAL documentation.
# Keep None until you have real, authorized documentation. Examples of the
# expected shape (NOT real endpoints):
#   "login":        {"method": "POST", "path": "/auth/login"}
#   "batches":      {"method": "GET",  "path": "/my/batches"}
#   "subjects":     {"method": "GET",  "path": "/batches/{batch_id}/subjects"}
# --------------------------------------------------------------------------
ENDPOINTS: dict[str, dict[str, str] | None] = {
    "login": None,
    "logout": None,
    "batches": None,
    "subjects": None,
    "topics": None,
    "lectures": None,
    "files": None,
    "file_meta": None,
    "download_url": None,
}

# CONFIGURATION POINT 2: how the token is sent. "bearer" | "header" | "cookie"
AUTH_STYLE: str = "bearer"
AUTH_HEADER_NAME: str = "Authorization"  # used when AUTH_STYLE == "header"

# --------------------------------------------------------------------------
# CONFIGURATION POINT 3: JSON field names, from the official docs.
# --------------------------------------------------------------------------
FIELD_MAP: dict[str, str] = {
    "token": "token",
    "token_expires_in": "expires_in",       # seconds, optional
    "list_root": "data",                     # key containing the result list
    "id": "id",
    "name": "name",
    "title": "title",
    "file_type": "type",
    "file_size": "size",
    "file_name": "filename",
    "file_url": "url",
    "published_at": "created_at",
    "lecture_number": "number",
    "validity": "validity",
}

_MISSING_MSG = (
    "❗ Official API not configured.\n\n"
    "This bot integrates ONLY through the source application's official/"
    "authorized API and will not guess endpoints.\n\n"
    "Required (from the vendor's official API documentation):\n"
    "• Base URL (.env APP_API_BASE_URL)\n"
    "• Login endpoint + auth token format\n"
    "• Endpoints for batches / subjects / topics / lectures / files\n"
    "• Authorized file download URL endpoint\n"
    "• JSON field names for each response\n\n"
    "Fill ENDPOINTS and FIELD_MAP in app_api/official_provider.py, "
    "or keep TEST_MODE=true to use the simulator."
)


class OfficialAppProvider(CourseProvider):
    """Real adapter - fully implemented HTTP client, configuration-driven."""

    def __init__(self) -> None:
        self._session: ProviderSession | None = None
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------ plumbing
    def _endpoint(self, key: str) -> dict[str, str]:
        cfg = ENDPOINTS.get(key)
        if not CONFIG.app_api_base_url or cfg is None:
            raise ProviderNotConfiguredError(_MISSING_MSG)
        return cfg

    def _client_or_create(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=CONFIG.app_api_base_url,
                timeout=httpx.Timeout(30.0),
                headers={"User-Agent": "CourseManagerBot/1.0 (authorized export)"},
            )
        return self._client

    def _auth_headers(self) -> dict[str, str]:
        if self._session is None or not self._session.token:
            raise SessionExpiredError("Not logged in. Use 🔐 Login first.")
        if self._session.expires_at and self._session.expires_at <= datetime.now(timezone.utc):
            raise SessionExpiredError("Session expired. Please log in again.")
        if AUTH_STYLE == "bearer":
            return {"Authorization": f"Bearer {self._session.token}"}
        if AUTH_STYLE == "header":
            return {AUTH_HEADER_NAME: self._session.token}
        return {}  # cookie style: httpx cookie jar keeps it

    async def _request(self, key: str, *, json_body: dict | None = None,
                       path_params: dict[str, str] | None = None,
                       authed: bool = True) -> Any:
        ep = self._endpoint(key)
        path = ep["path"].format(**(path_params or {}))
        headers = self._auth_headers() if authed else {}
        client = self._client_or_create()
        try:
            resp = await client.request(ep.get("method", "GET"), path,
                                        json=json_body, headers=headers)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise ProviderUnavailableError(f"Source API unreachable: {type(exc).__name__}") from exc

        if resp.status_code in (401,):
            raise SessionExpiredError("Session rejected by API (401). Log in again.")
        if resp.status_code in (403,):
            raise NotAuthorizedError("Your account is not authorized for this resource (403).")
        if resp.status_code >= 500:
            raise ProviderUnavailableError(f"Source API server error ({resp.status_code}).")
        if resp.status_code >= 400:
            raise AuthenticationError(f"Source API rejected the request ({resp.status_code}).")
        try:
            return resp.json()
        except ValueError as exc:
            raise ProviderUnavailableError("Source API returned invalid JSON.") from exc

    @staticmethod
    def _items(data: Any) -> list[dict]:
        root = FIELD_MAP.get("list_root", "")
        if isinstance(data, dict) and root and root in data:
            data = data[root]
        return data if isinstance(data, list) else []

    # ------------------------------------------------------------ interface
    async def login(self, username: str, password: str) -> ProviderSession:
        body = {"username": username, "password": password}
        if CONFIG.app_client_id:
            body["client_id"] = CONFIG.app_client_id
        if CONFIG.app_client_secret:
            body["client_secret"] = CONFIG.app_client_secret
        data = await self._request("login", json_body=body, authed=False)
        token = data.get(FIELD_MAP["token"]) if isinstance(data, dict) else None
        if not token:
            raise AuthenticationError("Login failed: no session token in API response.")
        expires_at = None
        ttl = data.get(FIELD_MAP.get("token_expires_in", ""), None) if isinstance(data, dict) else None
        if isinstance(ttl, (int, float)) and ttl > 0:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(ttl))
        self._session = ProviderSession(token=str(token), account_label=username,
                                        expires_at=expires_at)
        logger.info("Official API login OK for account label '%s'", username)
        return self._session

    async def logout(self) -> None:
        try:
            if ENDPOINTS.get("logout") and self._session:
                await self._request("logout", json_body={})
        except Exception:  # best effort
            pass
        finally:
            self._session = None
            if self._client is not None:
                await self._client.aclose()
                self._client = None

    def restore(self, session: ProviderSession) -> None:
        self._session = session

    async def get_batches(self) -> list[BatchInfo]:
        data = await self._request("batches")
        out: list[BatchInfo] = []
        for item in self._items(data):
            out.append(BatchInfo(
                id=str(item.get(FIELD_MAP["id"], "")),
                name=str(item.get(FIELD_MAP["name"], "")),
                validity=str(item.get(FIELD_MAP.get("validity", ""), "") or ""),
            ))
        return out

    async def get_subjects(self, batch_id: str) -> list[SubjectInfo]:
        data = await self._request("subjects", path_params={"batch_id": batch_id})
        return [SubjectInfo(id=str(i.get(FIELD_MAP["id"], "")), batch_id=batch_id,
                            name=str(i.get(FIELD_MAP["name"], "")))
                for i in self._items(data)]

    async def get_topics(self, batch_id: str, subject_id: str) -> list[TopicInfo]:
        data = await self._request("topics", path_params={"batch_id": batch_id,
                                                          "subject_id": subject_id})
        return [TopicInfo(id=str(i.get(FIELD_MAP["id"], "")), subject_id=subject_id,
                          name=str(i.get(FIELD_MAP["name"], "")))
                for i in self._items(data)]

    async def get_lectures(self, batch_id: str, topic_id: str) -> list[LectureInfo]:
        data = await self._request("lectures", path_params={"batch_id": batch_id,
                                                            "topic_id": topic_id})
        out: list[LectureInfo] = []
        for i in self._items(data):
            num = i.get(FIELD_MAP.get("lecture_number", ""), None)
            out.append(LectureInfo(id=str(i.get(FIELD_MAP["id"], "")), topic_id=topic_id,
                                   name=str(i.get(FIELD_MAP["name"], "")),
                                   number=int(num) if isinstance(num, (int, float)) else None))
        return out

    async def get_files(self, batch_id: str, lecture_id: str) -> list[FileInfo]:
        data = await self._request("files", path_params={"batch_id": batch_id,
                                                         "lecture_id": lecture_id})
        out: list[FileInfo] = []
        for i in self._items(data):
            size = i.get(FIELD_MAP.get("file_size", ""), None)
            out.append(FileInfo(
                id=str(i.get(FIELD_MAP["id"], "")),
                lecture_id=lecture_id,
                title=str(i.get(FIELD_MAP["title"], "")),
                file_type=str(i.get(FIELD_MAP["file_type"], "other")).lower(),
                file_size=int(size) if isinstance(size, (int, float)) else None,
                original_filename=str(i.get(FIELD_MAP.get("file_name", ""), "") or ""),
                published_at=str(i.get(FIELD_MAP.get("published_at", ""), "") or ""),
            ))
        return out

    async def get_file_metadata(self, file_id: str) -> FileInfo:
        data = await self._request("file_meta", path_params={"file_id": file_id})
        i = data if isinstance(data, dict) else {}
        root = FIELD_MAP.get("list_root", "")
        if root and isinstance(i.get(root), dict):
            i = i[root]
        size = i.get(FIELD_MAP.get("file_size", ""), None)
        return FileInfo(
            id=file_id,
            lecture_id=str(i.get("lecture_id", "")),
            title=str(i.get(FIELD_MAP["title"], "")),
            file_type=str(i.get(FIELD_MAP["file_type"], "other")).lower(),
            file_size=int(size) if isinstance(size, (int, float)) else None,
            original_filename=str(i.get(FIELD_MAP.get("file_name", ""), "") or ""),
        )

    async def get_download_url(self, file_id: str) -> str:
        data = await self._request("download_url", path_params={"file_id": file_id})
        url = data.get(FIELD_MAP["file_url"]) if isinstance(data, dict) else None
        if not url:
            raise NotAuthorizedError("API did not return an authorized download URL.")
        return str(url)
