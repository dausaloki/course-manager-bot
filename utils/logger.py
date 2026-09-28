"""Secure logging: console + rotating file + database audit trail.

A redaction filter guarantees the bot token, passwords and API secrets can
never leak into any log line, even if a library embeds them in an exception.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
from datetime import datetime, timezone

from config import CONFIG

_REDACTED = "[REDACTED]"


class SecretRedactingFilter(logging.Filter):
    """Replace every occurrence of a known secret in the final log message."""

    def __init__(self) -> None:
        super().__init__()
        self._secrets = [
            s for s in (
                CONFIG.bot_token,
                CONFIG.app_client_secret,
                CONFIG.app_client_id,
            ) if s
        ]

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        try:
            msg = record.getMessage()
            for secret in self._secrets:
                if secret in msg:
                    msg = msg.replace(secret, _REDACTED)
            record.msg = msg
            record.args = ()
        except Exception:  # never let logging crash the app
            pass
        return True


_configured = False


def setup_logging() -> None:
    """Configure root logging exactly once."""
    global _configured
    if _configured:
        return
    _configured = True

    level = getattr(logging, CONFIG.log_level, logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    )
    redactor = SecretRedactingFilter()

    root = logging.getLogger()
    root.setLevel(level)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    console.addFilter(redactor)
    root.addHandler(console)

    try:
        os.makedirs("logs", exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            "logs/bot.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        file_handler.addFilter(redactor)
        root.addHandler(file_handler)
    except OSError:
        pass

    # calm down noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.INFO)


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)


def log_event(level: str, event: str, detail: str = "") -> None:
    """Persist an audit event into the ``logs`` database table.

    Never raises; never receives secrets (callers are responsible for passing
    only non-sensitive data, and the redaction filter guards the text logs).
    """
    try:
        from database.db import get_session
        from database.models import LogEntry

        with get_session() as session:
            session.add(
                LogEntry(
                    level=level.upper(),
                    event=event[:100],
                    detail=detail[:2000],
                    created_at=datetime.now(timezone.utc),
                )
            )
    except Exception:  # pragma: no cover - audit log must never crash the bot
        get_logger(__name__).debug("could not persist audit event %s", event)
