"""Bot application factory: builds the single PTB Application, registers
all handlers and owns the background upload worker lifecycle."""
from __future__ import annotations

from telegram import Bot
from telegram.error import TelegramError
from telegram.ext import Application, ApplicationBuilder

from config import CONFIG
from telegram_bot.handlers import register_handlers
from telegram_bot.uploader import UploadWorker, destination_chat
from utils.logger import get_logger

logger = get_logger(__name__)


async def _verify_destination(bot: Bot) -> None:
    """Check the bot can reach and post to the destination chat."""
    if CONFIG.test_mode:
        logger.info("[TEST MODE] skipping destination permission check")
        return
    chat_id = destination_chat()
    try:
        chat = await bot.get_chat(chat_id)
        member = await bot.get_chat_member(chat.id, bot.id)
        if getattr(member, "can_post_messages", None) is False:
            logger.error("Bot lacks post permission in destination chat %s", chat_id)
        else:
            logger.info("Destination chat OK: %s", chat.title or chat_id)
    except TelegramError as exc:
        logger.error("Cannot access destination chat %s: %s — add the bot as "
                     "admin with post permission.", chat_id, exc)


async def _post_init(application: Application) -> None:
    worker = UploadWorker(application.bot, CONFIG.admin_user_id)
    application.bot_data["upload_worker"] = worker
    await _verify_destination(application.bot)
    # resume any queue left over from before the restart
    from services.queue_service import is_paused, pending_exists

    if pending_exists() and not is_paused():
        worker.ensure_running()
        logger.info("Resuming persistent upload queue from previous run")


async def _post_shutdown(application: Application) -> None:
    worker: UploadWorker | None = application.bot_data.get("upload_worker")
    if worker is not None:
        await worker.shutdown()


def build_application() -> Application:
    application = (
        ApplicationBuilder()
        .token(CONFIG.bot_token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    register_handlers(application)
    return application


def run() -> None:
    """Blocking entry point - starts long polling."""
    application = build_application()
    logger.info("Bot starting (test_mode=%s)", CONFIG.test_mode)
    application.run_polling(allowed_updates=["message", "callback_query"])
