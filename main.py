"""Entry point: validates configuration, initialises the database and
starts the single all-in-one Telegram bot."""
from __future__ import annotations

import sys

from config import CONFIG, validate_config
from database.migrations import init_db
from utils.logger import get_logger, setup_logging


def main() -> int:
    setup_logging()
    logger = get_logger("main")

    problems = validate_config(CONFIG)
    if problems:
        logger.error("Configuration problems found:")
        for p in problems:
            logger.error("  • %s", p)
        logger.error("Copy .env.example to .env and fill in the values.")
        return 1

    init_db()

    from telegram_bot.bot import run

    logger.info("Starting Course Manager Bot (TEST_MODE=%s)", CONFIG.test_mode)
    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
