"""Caption/message formatting with an admin-configurable template.

Placeholders: {index} {title} {topic} {subject} {batch} {lecture}
              {file_type} {date}
Unknown data is rendered as an empty string - metadata is never invented
and the original title is never modified.
"""
from __future__ import annotations

from database.db import DEFAULT_SETTINGS, get_setting

TELEGRAM_CAPTION_LIMIT = 1024


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:  # pragma: no cover - trivial
        return ""


def current_template() -> str:
    return get_setting("caption_template",
                       DEFAULT_SETTINGS["caption_template"])


def render_caption(index: int | str, context: dict[str, str],
                   template: str | None = None) -> str:
    """Render the upload caption; always fits Telegram's 1024-char limit."""
    template = template if template is not None else current_template()
    fields = _SafeDict(
        index=str(index),
        title=context.get("title", ""),
        topic=context.get("topic", ""),
        subject=context.get("subject", ""),
        batch=context.get("batch", ""),
        lecture=context.get("lecture", ""),
        file_type=context.get("file_type", ""),
        date=context.get("date", ""),
    )
    caption = template.format_map(fields)
    if len(caption) > TELEGRAM_CAPTION_LIMIT:
        caption = caption[: TELEGRAM_CAPTION_LIMIT - 1] + "…"
    return caption
