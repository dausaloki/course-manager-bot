"""Authorization helpers - single admin model.

Only ``ADMIN_USER_ID`` may use administrative features.  This module contains
the check used by every handler plus small helpers for masking identifiers in
user-facing text.
"""
from __future__ import annotations

import functools
from typing import Any, Awaitable, Callable

from telegram import Update
from telegram.ext import ContextTypes

from config import CONFIG
from utils.logger import get_logger, log_event

logger = get_logger(__name__)

HandlerFunc = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[Any]]


def is_admin(user_id: int | None) -> bool:
    """True only for the configured administrator."""
    return user_id is not None and CONFIG.admin_user_id > 0 and user_id == CONFIG.admin_user_id


def admin_only(func: HandlerFunc) -> HandlerFunc:
    """Decorator: reject every non-admin interaction politely and audit it."""

    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Any:
        user = update.effective_user
        if user is None or not is_admin(user.id):
            uid = user.id if user else "unknown"
            logger.warning("Unauthorized access attempt by user %s", uid)
            log_event("WARNING", "unauthorized_access", f"user_id={uid}")
            if update.callback_query:
                await update.callback_query.answer("⛔ Unauthorized", show_alert=True)
            elif update.effective_message:
                await update.effective_message.reply_text(
                    "⛔ This bot is private. You are not authorized."
                )
            return None
        return await func(update, context)

    return wrapper


def mask(value: str, keep: int = 4) -> str:
    """Mask a sensitive string, keeping only the last ``keep`` characters."""
    if not value:
        return ""
    if len(value) <= keep:
        return "*" * len(value)
    return "*" * (len(value) - keep) + value[-keep:]
