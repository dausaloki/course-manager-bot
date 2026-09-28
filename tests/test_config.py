"""Configuration tests: env parsing + validation messages."""
from __future__ import annotations

from dataclasses import replace

from config import Config, _as_bool, _as_int, validate_config


def _base_cfg(**overrides) -> Config:
    cfg = Config(
        bot_token="123:ABC", chat_id="-100123", admin_user_id=42,
        app_api_base_url="", app_client_id="", app_client_secret="",
        database_url="sqlite:///:memory:", test_mode=True,
        log_level="INFO", index_start=1,
    )
    return replace(cfg, **overrides)


def test_valid_config_has_no_problems():
    assert validate_config(_base_cfg()) == []


def test_missing_essentials_reported():
    problems = validate_config(_base_cfg(bot_token="", chat_id="", admin_user_id=0))
    assert len(problems) == 3
    joined = " ".join(problems)
    assert "TELEGRAM_BOT_TOKEN" in joined
    assert "TELEGRAM_CHAT_ID" in joined
    assert "ADMIN_USER_ID" in joined


def test_real_mode_requires_api_base_url():
    problems = validate_config(_base_cfg(test_mode=False, app_api_base_url=""))
    assert any("APP_API_BASE_URL" in p for p in problems)
    # configured -> fine
    assert validate_config(_base_cfg(test_mode=False,
                                     app_api_base_url="https://api.example")) == []


def test_bool_parsing():
    assert _as_bool("true") and _as_bool("1") and _as_bool("YES") and _as_bool("on")
    assert not _as_bool("false") and not _as_bool("0") and not _as_bool("off")
    assert _as_bool(None, default=True) is True


def test_int_parsing():
    assert _as_int("7") == 7
    assert _as_int("x", 3) == 3
    assert _as_int(None, 5) == 5
