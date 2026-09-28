"""Authorization tests: only ADMIN_USER_ID may use the bot."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from utils.security import admin_only, is_admin, mask


def test_is_admin_matches_config():
    with patch("utils.security.CONFIG", SimpleNamespace(admin_user_id=12345)):
        assert is_admin(12345) is True
        assert is_admin(99999) is False
        assert is_admin(None) is False


def test_is_admin_rejects_when_unconfigured():
    with patch("utils.security.CONFIG", SimpleNamespace(admin_user_id=0)):
        assert is_admin(0) is False
        assert is_admin(123) is False


def test_admin_only_blocks_stranger():
    called = {"n": 0}

    @admin_only
    async def secret(update, context):
        called["n"] += 1
        return "ok"

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=666),
        callback_query=None,
        effective_message=SimpleNamespace(reply_text=AsyncMock()),
    )
    with patch("utils.security.CONFIG", SimpleNamespace(admin_user_id=12345)):
        result = asyncio.run(secret(update, None))
    assert result is None
    assert called["n"] == 0
    update.effective_message.reply_text.assert_awaited()


def test_admin_only_allows_admin():
    @admin_only
    async def secret(update, context):
        return "ok"

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=12345),
        callback_query=None,
        effective_message=None,
    )
    with patch("utils.security.CONFIG", SimpleNamespace(admin_user_id=12345)):
        assert asyncio.run(secret(update, None)) == "ok"


def test_mask_hides_secrets():
    assert mask("supersecrettoken", keep=4).endswith("oken")
    assert "supersecret" not in mask("supersecrettoken")
    assert mask("ab") == "**"
    assert mask("") == ""
