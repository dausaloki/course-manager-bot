"""Small shared helpers: pagination, formatting, chunking."""
from __future__ import annotations

from typing import Sequence, TypeVar

T = TypeVar("T")

PER_PAGE = 8


def paginate(items: Sequence[T], page: int, per_page: int = PER_PAGE) -> tuple[list[T], int, int]:
    """Return ``(page_items, page, total_pages)`` with the page clamped to range."""
    total_pages = max(1, (len(items) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    return list(items[start:start + per_page]), page, total_pages


def human_size(num_bytes: int | None) -> str:
    """Human readable file size (never invents data: '' when unknown)."""
    if not num_bytes or num_bytes <= 0:
        return ""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return ""


def truncate(text: str, limit: int = 40) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def file_type_icon(file_type: str) -> str:
    ft = (file_type or "").lower()
    if ft == "video":
        return "🎥"
    if ft == "pdf":
        return "📄"
    return "📁"
