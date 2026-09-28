"""Central configuration loaded from environment variables (.env supported).

Secrets are never hard-coded and never logged.  ``validate_config`` is called
by ``main.py`` at startup and produces human readable error messages instead
of stack traces when something essential is missing.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: str | None, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


DEFAULT_DATABASE_URL = "sqlite:///course_manager.db"


def _normalize_db_url(url: str | None) -> str:
    """Make DATABASE_URL deployment-proof.

    - Empty/blank value (e.g. a broken Railway reference) falls back to the
      SQLite default instead of crashing ``create_engine('')``.
    - ``postgres://`` and ``postgresql://`` (what Railway/Heroku provide)
      are rewritten to ``postgresql+psycopg://`` so SQLAlchemy uses the
      installed psycopg v3 driver.
    """
    url = (url or "").strip()
    if not url:
        return DEFAULT_DATABASE_URL
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


@dataclass(frozen=True)
class Config:
    """Immutable runtime configuration."""

    bot_token: str
    chat_id: str
    admin_user_id: int
    app_api_base_url: str
    app_client_id: str
    app_client_secret: str
    database_url: str
    test_mode: bool
    log_level: str
    index_start: int


def load_config() -> Config:
    """Read configuration from the environment (tolerant: validation is separate)."""
    return Config(
        bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
        admin_user_id=_as_int(os.getenv("ADMIN_USER_ID"), 0),
        app_api_base_url=os.getenv("APP_API_BASE_URL", "").strip(),
        app_client_id=os.getenv("APP_CLIENT_ID", "").strip(),
        app_client_secret=os.getenv("APP_CLIENT_SECRET", "").strip(),
        database_url=_normalize_db_url(os.getenv("DATABASE_URL")),
        test_mode=_as_bool(os.getenv("TEST_MODE"), True),
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
        index_start=_as_int(os.getenv("INDEX_START"), 1),
    )


CONFIG: Config = load_config()


def validate_config(cfg: Config) -> list[str]:
    """Return a list of configuration problems (empty list == OK)."""
    problems: list[str] = []
    if not cfg.bot_token:
        problems.append("TELEGRAM_BOT_TOKEN is missing. Create a bot with @BotFather.")
    if not cfg.chat_id:
        problems.append("TELEGRAM_CHAT_ID is missing (destination channel/group id).")
    if cfg.admin_user_id <= 0:
        problems.append("ADMIN_USER_ID is missing or invalid (numeric Telegram user id).")
    if not cfg.test_mode and not cfg.app_api_base_url:
        problems.append(
            "TEST_MODE=false but APP_API_BASE_URL is empty. Provide the OFFICIAL "
            "authorized API base URL, or keep TEST_MODE=true."
        )
    return problems
