"""Caption formatter tests."""
from __future__ import annotations

from telegram_bot.formatter import TELEGRAM_CAPTION_LIMIT, render_caption


CONTEXT = {
    "title": "Lecture-35 | राजस्थान : सिंचाई परियोजना नमस्ते.mp4",
    "topic": "Geography",
    "subject": "Geography",
    "batch": "सम्पूर्ण राजस्थान GK - Complete Online Batch",
    "lecture": "Lecture 35",
    "file_type": "video",
    "date": "2026-01-15",
}


def test_default_template(fresh_db):
    caption = render_caption(204, CONTEXT)
    assert "Index: 204" in caption
    assert "Title: Lecture-35 | राजस्थान : सिंचाई परियोजना नमस्ते.mp4" in caption
    assert "Topic: Geography" in caption
    assert "Batch: सम्पूर्ण राजस्थान GK - Complete Online Batch" in caption


def test_custom_template(fresh_db):
    caption = render_caption(7, CONTEXT, template="#{index} {title} [{file_type}]")
    assert caption.startswith("#7 ")
    assert caption.endswith("[video]")


def test_missing_fields_render_empty(fresh_db):
    caption = render_caption(1, {}, template="A{title}B{topic}C")
    assert caption == "ABC"


def test_title_never_modified(fresh_db):
    caption = render_caption(1, CONTEXT, template="{title}")
    assert caption == CONTEXT["title"]


def test_caption_length_capped(fresh_db):
    caption = render_caption(1, {"title": "x" * 5000}, template="{title}")
    assert len(caption) <= TELEGRAM_CAPTION_LIMIT


def test_admin_configurable_template(fresh_db):
    from database.db import set_setting

    set_setting("caption_template", "IDX={index} | {batch}")
    caption = render_caption(204, CONTEXT)
    assert caption == "IDX=204 | सम्पूर्ण राजस्थान GK - Complete Online Batch"
