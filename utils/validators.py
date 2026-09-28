"""Input validation for settings and user text input."""
from __future__ import annotations

import re


class ValidationError(ValueError):
    """Raised when user input fails validation; message is user-safe."""


def validate_username(value: str) -> str:
    value = value.strip()
    if not value or len(value) > 190:
        raise ValidationError("Username/ID must be 1-190 characters.")
    if any(c in value for c in "\n\r\t"):
        raise ValidationError("Username/ID contains invalid characters.")
    return value


def validate_password(value: str) -> str:
    if not value or len(value) > 500:
        raise ValidationError("Password must be 1-500 characters.")
    return value


def validate_chat_id(value: str) -> str:
    value = value.strip()
    if not re.fullmatch(r"@[A-Za-z0-9_]{4,32}|-?\d{5,20}", value):
        raise ValidationError(
            "Chat id must be numeric (e.g. -1001234567890) or a public @username."
        )
    return value


def validate_int_range(value: str, lo: int, hi: int, name: str) -> int:
    try:
        n = int(value.strip())
    except ValueError as exc:
        raise ValidationError(f"{name} must be a whole number.") from exc
    if not lo <= n <= hi:
        raise ValidationError(f"{name} must be between {lo} and {hi}.")
    return n


def validate_caption_template(value: str) -> str:
    value = value.strip()
    if not value or len(value) > 900:
        raise ValidationError("Caption template must be 1-900 characters.")
    allowed = {"index", "title", "topic", "subject", "batch", "lecture", "file_type", "date"}
    placeholders = set(re.findall(r"\{([a-z_]+)\}", value))
    unknown = placeholders - allowed
    if unknown:
        raise ValidationError(
            "Unknown placeholder(s): "
            + ", ".join(sorted("{" + u + "}" for u in unknown))
            + ". Allowed: " + ", ".join(sorted("{" + a + "}" for a in allowed))
        )
    return value


def validate_search_query(value: str) -> str:
    value = value.strip()
    if not value or len(value) > 200:
        raise ValidationError("Search query must be 1-200 characters.")
    return value
