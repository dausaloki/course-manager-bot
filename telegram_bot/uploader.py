"""Background upload worker.

- Claims items from the persistent queue (controlled concurrency,
  Telegram-friendly pacing: minimum 3 s between sends).
- Downloads via the provider's *authorized* URL, then sends to the
  configured destination chat with the rendered caption.
- Reuses an existing Telegram file_id when the same file was already
  uploaded (no unnecessary re-upload of bytes).
- Temporary errors retry with exponential backoff; permanent errors fail
  immediately.  All state is persisted, so the queue survives restarts.
- In TEST_MODE no real file is transferred: uploads are simulated.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import uuid

import httpx
from telegram import Bot
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TimedOut

from app_api.provider import (
    NotAuthorizedError,
    ProviderNotConfiguredError,
    ProviderUnavailableError,
    SessionExpiredError,
)
from config import CONFIG
from database.db import allocate_index, get_session, get_setting
from database.models import QueueStatus, TelegramUpload
from services import course_service, queue_service, upload_service
from telegram_bot.formatter import render_caption
from utils.logger import get_logger, log_event

logger = get_logger(__name__)

SEND_MIN_INTERVAL = 3.0  # seconds between sends (Telegram-friendly)


class PermanentUploadError(Exception):
    """Errors that must not be retried automatically."""


def destination_chat() -> str:
    return get_setting("destination_chat_id", "") or CONFIG.chat_id


class UploadWorker:
    """Singleton asyncio worker owned by the PTB application."""

    def __init__(self, bot: Bot, admin_id: int) -> None:
        self.bot = bot
        self.admin_id = admin_id
        self._task: asyncio.Task | None = None
        self._send_lock = asyncio.Lock()
        self._stop = asyncio.Event()
        self._processed_since_idle = 0
        self._failed_since_idle = 0
        self._test_msg_counter = 100_000

    # ------------------------------------------------------------ lifecycle
    def ensure_running(self) -> None:
        if self._task is None or self._task.done():
            self._stop.clear()
            self._task = asyncio.create_task(self._run(), name="upload-worker")
            logger.info("Upload worker started")

    async def shutdown(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    # ------------------------------------------------------------ main loop
    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                if queue_service.is_paused():
                    await asyncio.sleep(2)
                    continue
                item = queue_service.claim_next()
                if item is None:
                    if self._processed_since_idle and not queue_service.pending_exists():
                        await self._notify_completion()
                    await asyncio.sleep(2)
                    continue
                await self._process_item(item.id, item.source_file_id, item.force)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # the worker must never die
                logger.exception("worker loop error: %s", exc)
                await asyncio.sleep(3)

    async def _process_item(self, item_id: int, source_file_pk: int, force: bool) -> None:
        max_retries = int(get_setting("retry_count", "3") or 3)
        try:
            # 1. duplicate safety net (normally filtered at enqueue time)
            existing = upload_service.find_existing_upload(source_file_pk)
            reuse_file_id = ""
            if existing is not None:
                if not force:
                    queue_service.mark_completed(item_id)
                    logger.info("Item %s already uploaded as index %s - skipped",
                                item_id, existing.index_no)
                    return
                reuse_file_id = existing.telegram_file_id
            else:
                reuse_file_id = upload_service.find_reusable_file_id(source_file_pk)

            context = course_service.file_context(source_file_pk)
            if not context:
                raise PermanentUploadError("Source file metadata missing from database.")

            # 2. send + record (index is allocated exactly once inside)
            await self._send_and_record(source_file_pk, context, reuse_file_id)
            queue_service.mark_completed(item_id)
            self._processed_since_idle += 1

        except PermanentUploadError as exc:
            queue_service.mark_failed(item_id, str(exc), permanent=True,
                                      max_retries=max_retries)
            self._failed_since_idle += 1
        except (Forbidden, BadRequest, NotAuthorizedError,
                ProviderNotConfiguredError, SessionExpiredError) as exc:
            queue_service.mark_failed(item_id, f"{type(exc).__name__}: {exc}",
                                      permanent=True, max_retries=max_retries)
            self._failed_since_idle += 1
        except (RetryAfter, TimedOut, NetworkError, ProviderUnavailableError,
                httpx.TransportError, httpx.TimeoutException) as exc:
            status = queue_service.mark_failed(item_id, f"{type(exc).__name__}: {exc}",
                                               permanent=False, max_retries=max_retries)
            if status == QueueStatus.FAILED:
                self._failed_since_idle += 1
            if isinstance(exc, RetryAfter):
                await asyncio.sleep(float(exc.retry_after) + 1)
        except Exception as exc:  # unexpected -> limited retries
            logger.exception("Unexpected upload error for item %s", item_id)
            status = queue_service.mark_failed(item_id, f"Unexpected: {exc}",
                                               permanent=False, max_retries=max_retries)
            if status == QueueStatus.FAILED:
                self._failed_since_idle += 1

    # ------------------------------------------------------------ sending
    async def _send_and_record(self, source_file_pk: int, context: dict[str, str],
                               reuse_file_id: str) -> None:
        """Send one file and persist the TelegramUpload record."""
        chat_id = destination_chat()
        index_no = allocate_index()  # unique, restart-safe, transaction-protected
        caption = render_caption(index_no, context)
        file_type = context.get("file_type", "other")

        if CONFIG.test_mode:
            await asyncio.sleep(0.4)  # simulate transfer time
            self._test_msg_counter += 1
            tg_file_id = f"TEST-FILE-{uuid.uuid4().hex[:12]}"
            message_id: int | None = self._test_msg_counter
            logger.info("[TEST MODE] simulated upload '%s' -> chat %s (index %s)",
                        context.get("title", ""), chat_id, index_no)
        else:
            async with self._send_lock:  # serialize sends = gentle rate limit
                if reuse_file_id:
                    msg = await self._tg_send(chat_id, file_type, reuse_file_id, caption)
                else:
                    provider = course_service.get_provider(self.admin_id)
                    src = course_service.get_file(source_file_pk)
                    if src is None:
                        raise PermanentUploadError("Source file row disappeared.")
                    url = await provider.get_download_url(src.source_id)
                    tmp_path = await self._download(url, src.original_filename or src.title)
                    try:
                        with open(tmp_path, "rb") as fh:
                            msg = await self._tg_send(chat_id, file_type, fh, caption,
                                                      filename=os.path.basename(tmp_path))
                    finally:
                        try:
                            os.unlink(tmp_path)
                        except OSError:
                            pass
                await asyncio.sleep(SEND_MIN_INTERVAL)
            tg_file_id = ""
            if msg.video:
                tg_file_id = msg.video.file_id
            elif msg.document:
                tg_file_id = msg.document.file_id
            message_id = msg.message_id

        with get_session() as session:
            session.add(TelegramUpload(
                index_no=index_no,
                source_file_id=source_file_pk,
                telegram_file_id=tg_file_id or "",
                message_id=message_id,
                chat_id=str(chat_id),
                status=QueueStatus.COMPLETED,
            ))
        log_event("INFO", "upload_completed",
                  f"index={index_no} source_file={source_file_pk} msg={message_id}")

    async def _tg_send(self, chat_id: str, file_type: str, payload, caption: str,
                       filename: str | None = None):
        if file_type == "video":
            return await self.bot.send_video(
                chat_id=chat_id, video=payload, caption=caption,
                supports_streaming=True,
                read_timeout=300, write_timeout=300, connect_timeout=60,
            )
        return await self.bot.send_document(
            chat_id=chat_id, document=payload, caption=caption,
            filename=filename,
            read_timeout=300, write_timeout=300, connect_timeout=60,
        )

    async def _download(self, url: str, name_hint: str) -> str:
        """Stream an *authorized* URL to a temporary file."""
        suffix = os.path.splitext(name_hint)[1][:10] or ".bin"
        fd, path = tempfile.mkstemp(prefix="cmb_", suffix=suffix)
        os.close(fd)
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0),
                                         follow_redirects=True) as client:
                async with client.stream("GET", url) as resp:
                    if resp.status_code in (401, 403):
                        raise PermanentUploadError(
                            f"Download not authorized ({resp.status_code}).")
                    if resp.status_code >= 400:
                        raise ProviderUnavailableError(
                            f"Download failed ({resp.status_code}).")
                    with open(path, "wb") as out:
                        async for chunk in resp.aiter_bytes(1024 * 256):
                            out.write(chunk)
            return path
        except Exception:
            try:
                os.unlink(path)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------ notify
    async def _notify_completion(self) -> None:
        processed = self._processed_since_idle
        failed = self._failed_since_idle
        self._processed_since_idle = 0
        self._failed_since_idle = 0
        if get_setting("notifications", "on") != "on":
            return
        try:
            await self.bot.send_message(
                chat_id=self.admin_id,
                text=(
                    "✅ Upload completed\n\n"
                    f"Total: {processed + failed}\n"
                    f"Successful: {processed}\n"
                    f"Failed: {failed}"
                ),
            )
        except Exception as exc:
            logger.warning("could not send completion notice: %s", exc)
